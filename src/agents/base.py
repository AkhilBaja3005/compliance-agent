"""Shared agent plumbing: context, verdicts, evidence helpers, finding assembly."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from typing import Literal

from src.edge_extractors import TriModalIndex
from src.regulatory_rag import CompanyProfile, MandatoryCheck
from src.regulatory_rag.tier_b_index import HybridRetriever
from src.schemas.artifacts import ASTSlice, BehavioralCapabilityCard, DependencyFact, DocumentChunk
from src.schemas.findings import ComplianceFinding, EvidencePointer, FindingStatus, RiskTier

from .llm_client import LLMClient, Narrative

ART50_APPLIES = date(2026, 8, 2)
ART50_LEGACY_DEADLINE = date(2026, 12, 2)


@dataclass
class AuditContext:
    index: TriModalIndex
    profile: CompanyProfile
    llm: LLMClient
    retriever: HybridRetriever
    law_store: object
    linkup: object | None = None  # LinkupLicenseVerifier
    compliance_store: object | None = None  # MongoComplianceStore (Atlas or in-memory fallback)


@dataclass
class Verdict:
    status: FindingStatus
    confidence: float
    title: str
    summary: str
    evidence: list[EvidencePointer] = field(default_factory=list)
    drift: str | None = None
    risk_tier: RiskTier | None = None
    scan_basis: bool = False  # evidence-free PASS justified by an explicit exhaustive scan
    citation_urls: list[str] = field(default_factory=list)  # Linkup-verified sources
    context: str = ""  # pruned prompt context (claim + mismatched lines + tags); never whole files


def snippet(text: str, n: int = 280) -> str:
    t = " ".join(text.split())
    return t if len(t) <= n else t[: n - 1] + "…"


def ev_slice(s: ASTSlice) -> EvidencePointer:
    return EvidencePointer(source_type="code", artifact_id=s.slice_id, exact_locator=s.locator,
                           sha256_hash=s.sha256_hash, snippet=snippet(s.code_snippet))


def ev_card(c: BehavioralCapabilityCard) -> EvidencePointer:
    return EvidencePointer(source_type="capability_card", artifact_id=c.module_id, exact_locator=c.exact_locator,
                           sha256_hash=c.sha256_hash,
                           snippet=snippet((c.system_prompt or "(no system prompt)") + " | tags=" + ",".join(c.capability_tags)))


def ev_chunk(d: DocumentChunk, text: str | None = None) -> EvidencePointer:
    return EvidencePointer(source_type="doc", artifact_id=d.chunk_id, exact_locator=d.locator,
                           sha256_hash=d.sha256_hash, snippet=snippet(text or d.text))


def ev_dep(d: DependencyFact) -> EvidencePointer:
    return EvidencePointer(source_type="dependency", artifact_id=d.dep_id, exact_locator=d.locator,
                           sha256_hash=d.sha256_hash, snippet=snippet(d.snippet))


def ev_data(a: dict, note: str = "") -> EvidencePointer:
    cols = ", ".join(f"{c['name']}[{'/'.join(c['classes'])}]" for c in a.get("columns", []) if c.get("classes"))[:200]
    return EvidencePointer(source_type="data_asset", artifact_id=a["asset_id"], exact_locator=f"{a['path']}:1-1", sha256_hash=a["sha256_hash"],
                           snippet=snippet(f"{a['kind']} · {len(a.get('columns', []))} column(s) · classified: {cols or 'none'}. {note}".strip()))


def ev_pdf_chunk(chunk_dict: dict) -> EvidencePointer:
    loc = chunk_dict.get("exact_locator") or f"{chunk_dict.get('filename')}#page={chunk_dict.get('page_number', 1)}"
    sha = chunk_dict.get("sha256_hash", "")
    art_id = chunk_dict.get("chunk_id") or chunk_dict.get("filename", "regulatory.pdf")
    snip = snippet(chunk_dict.get("text", ""))
    return EvidencePointer(
        source_type="Regulatory PDF",
        artifact_id=art_id,
        exact_locator=loc,
        sha256_hash=sha,
        snippet=snip,
        type="Regulatory PDF",
        item=chunk_dict.get("filename", "regulatory.pdf"),
    )


# ---- index selectors shared by agents
def external_entries(ix: TriModalIndex) -> list[ASTSlice]:
    return [s for s in ix.slices if s.is_entrypoint and (s.calls_ai_sdk or s.calls_http or s.external_endpoints)]


def generation_entries(ix: TriModalIndex) -> list[ASTSlice]:
    return [s for s in ix.slices if s.is_entrypoint and s.is_generation]


def decision_candidates(ix: TriModalIndex) -> tuple[list[ASTSlice], bool]:
    """Decision entry points; falls back to all external entries in high-risk sectors (closed-world)."""
    dec = [s for s in ix.slices if s.is_entrypoint and s.is_decision]
    if dec:
        return dec, True
    from src.regulatory_rag.tier_a_rules import HIGH_RISK_SECTORS

    return (external_entries(ix), False) if ix.sector in HIGH_RISK_SECTORS else ([], False)


def slice_regions(s: ASTSlice) -> set[str]:
    return set(s.endpoint_regions.values()) or {"UNKNOWN"}


def pii_likely(s: ASTSlice, ix: TriModalIndex) -> bool:
    from src.edge_extractors.code_scanner import PII_INDICATOR_RE
    from src.regulatory_rag.tier_a_rules import HIGH_RISK_SECTORS

    if ix.sector in HIGH_RISK_SECTORS or PII_INDICATOR_RE.search(s.code_snippet):
        return True
    # callee helpers in the same file may build the payload
    return any(PII_INDICATOR_RE.search(o.code_snippet) for o in ix.slices if o.file_path == s.file_path)


def no_code_verdict(title: str) -> Verdict:
    return Verdict("SUSPECTED_GAP", 0.6, title,
                   "No Python source was found for this tenant, so the control cannot be verified (closed-world: no evidence ≠ pass).")


class MicroAgent:
    name = "base"

    def evaluate(self, check: MandatoryCheck, ctx: AuditContext) -> Verdict:  # pragma: no cover - abstract
        raise NotImplementedError

    def run(self, check: MandatoryCheck, ctx: AuditContext) -> ComplianceFinding:
        v = self.evaluate(check, ctx)
        return assemble_finding(check, v, ctx)


def assemble_finding(check: MandatoryCheck, v: Verdict, ctx: AuditContext) -> ComplianceFinding:
    status, summary = v.status, v.summary
    # Closed-World Assumption: a PASS needs explicit positive evidence (or an explicit exhaustive scan basis).
    if status == "PASS" and not v.evidence and not v.scan_basis:
        status = "SUSPECTED_GAP"
        summary += " [closed-world: PASS withheld, no explicit positive evidence]"
    rule = ctx.law_store.get(check.regulatory_reference)
    if rule is not None:
        summary += f" Basis: {rule.reference} — {rule.text[:150].rstrip()}…"
    try:
        hits = ctx.retriever.retrieve(f"{check.question} {v.title}", k=2)
        related = [h.rule.rule_id for h in hits if h.rule.rule_id != check.regulatory_reference][:1]
        if related:
            summary += f" Related: {related[0]}."
    except Exception:
        pass
    # Attach retrieved Regulatory PDF citations if available
    try:
        pdf_hits = ctx.retriever.search_regulatory_knowledge(f"{check.question} {v.title}", top_k=2)
        for ph in pdf_hits:
            if ph.get("source_type") in ("REGULATORY_PDF", "COMPANY_DOC") or "page" in str(ph.get("exact_locator", "")):
                # If finding has less than 4 evidence pointers, append PDF chunk pointer
                if len(v.evidence) < 5:
                    v.evidence.append(ev_pdf_chunk(ph))
    except Exception:
        pass
    narrative = ctx.llm.structured(
        "You rewrite compliance audit summaries concisely. Never change facts, status or numbers.",
        f"Check: {check.question}\nStatus: {status}\nSummary: {summary}" + (f"\nEvidence context:\n{v.context}" if v.context else ""), Narrative, lambda: Narrative(summary=summary))
    final_summary = narrative.summary if narrative.summary.strip() else summary
    urls = list(dict.fromkeys(v.citation_urls + ([rule.linkup_source_url] if rule is not None and rule.linkup_source_url else [])))
    return ComplianceFinding(
        linkup_citation_urls=urls,
        finding_id=f"{ctx.index.tenant_id}-{check.check_id}", tenant_id=ctx.index.tenant_id,
        jurisdiction=check.jurisdiction, regulatory_reference=check.regulatory_reference,
        risk_tier=v.risk_tier or check.risk_tier, status=status, confidence_score=v.confidence,
        title=v.title, summary=final_summary, code_vs_doc_drift=v.drift, evidence=v.evidence, check_id=check.check_id,
    )

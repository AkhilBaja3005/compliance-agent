"""Pure, offline snapshot auditing and per-function regression identities."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from src.agents.base import AuditContext, Verdict, assemble_finding, decision_candidates, external_entries
from src.agents.enrichment import enrich_findings
from src.agents import report_builder
from src.agents.hitl_oversight_agent import oversight_verdict
from src.agents.pii_flow_agent import redaction_verdict
from src.agents.supervisor import AGENTS
from src.edge_extractors import TriModalIndex, build_systems
from src.edge_extractors.code_scanner import scan_code
from src.edge_extractors.doc_parser import extract_assertions, parse_documents
from src.guardrails import apply_guardrails
from src.law_sync.store import LawStore
from src.regulatory_rag import build_checklist, build_profile
from src.regulatory_rag.tier_b_index import HybridRetriever
from src.schemas.artifacts import sha256_text
from src.schemas.findings import TriagedAuditReport

from .policy import Policy

SCANNER_VERSION = "git-gate-v1"


class OfflineNarrative:
    def structured(self, system, user, schema, fallback):
        return fallback()


@dataclass
class SnapshotResult:
    report: TriagedAuditReport
    instances: dict[str, dict]

    @property
    def confirmed(self) -> dict[str, dict]:
        return {f.finding_id: {**self.instances[f.finding_id], "finding": f.model_dump(mode="json")}
                for f in self.report.confirmed_findings if f.finding_id in self.instances}


class SnapshotAuditor:
    def __init__(self, policy: Policy):
        self.policy = policy
        self.laws = LawStore()  # private, versioned seed snapshot; no global sync state
        self.retriever = HybridRetriever(self.laws, local_only=True)
        self.assessed_at = datetime.now(timezone.utc)

    def evaluate(self, root: Path, commit: str | None) -> SnapshotResult:
        p = self.policy
        scan = scan_code(root, p.tenant_id, strict=True)
        chunks = parse_documents(root, p.tenant_id)
        ix = TriModalIndex(tenant_id=p.tenant_id, company_name=p.company_name, sector=p.sector,
                           commercial=p.commercial, slices=scan.slices, cards=scan.cards, chunks=chunks,
                           assertions=extract_assertions(chunks), dependencies=scan.dependencies,
                           py_files=scan.py_files, uses_local_model=scan.uses_local_model,
                           commit_sha=commit, code_origin="git-object", docs_origin="git-object")
        for sl in ix.slices:
            sl.commit_sha, sl.origin = commit, "git-object"
        for card in ix.cards:
            card.commit_sha = commit
        build_systems(ix, [])
        profile = build_profile(ix)
        checks, _ = build_checklist(profile, frameworks=None)
        ctx = AuditContext(ix, profile, OfflineNarrative(), self.retriever, self.laws)
        findings, instances, trace = [], {}, []
        for check in checks:
            if check.check_id in p.blocking_checks:
                if check.check_id == "PII-01":
                    entries = [(s, redaction_verdict(s, ix)) for s in external_entries(ix)]
                else:
                    cands, explicit = decision_candidates(ix)
                    entries = [(s, oversight_verdict(s, explicit)) for s in cands]
                if entries:
                    for sl, verdict in entries:
                        symbol = sl.qualified_name or sl.function_name
                        key = sha256_text(f"{p.repository}\0{check.check_id}\0{sl.file_path}\0{symbol}")
                        f = assemble_finding(check, verdict, ctx)
                        f.finding_id = f"{p.tenant_id}-{check.check_id}-{key}"
                        instances[f.finding_id] = {"check_id": check.check_id, "file_path": sl.file_path,
                                                   "qualified_name": symbol, "exact_locator": sl.locator}
                        findings.append(f)
                    continue
            agent = AGENTS[check.agent]
            try:
                # Skip the tracing decorator rather than trusting ambient credentials to be absent.
                evaluate = getattr(agent.evaluate, "__wrapped__", None)
                verdict = evaluate(agent, check, ctx) if evaluate else agent.evaluate(check, ctx)
            except Exception as exc:
                if check.check_id in p.blocking_checks:
                    raise RuntimeError(f"Required check {check.check_id} failed") from exc
                verdict = Verdict("SUSPECTED_GAP", 0.0, f"{check.check_id}: advisory check failed",
                                  f"Advisory agent raised {type(exc).__name__}; review required.")
            findings.append(assemble_finding(check, verdict, ctx))
        findings = enrich_findings(findings, checks, ix, self.laws, self.assessed_at)
        report = apply_guardrails(findings, ix, trace, law_store=self.laws)
        report.assessed_at = self.assessed_at
        report.rule_library_version = self.laws.version
        report.scope = "Offline Git snapshot; ALL frameworks; selected regression policies"
        report.system_inventory = ix.systems
        report.input_coverage, report.input_coverage_pct = report_builder.build_input_coverage(ix)
        report.overall_readiness, report.readiness_summary = report_builder.readiness(report.all_findings())
        report.compliance_matrix = report_builder.build_compliance_matrix(report.all_findings(), self.laws)
        report.bundle_sha256 = report_builder.bundle_hash(report.all_findings())
        report.roadmap = report_builder.build_roadmap(report.all_findings())
        report.eval_results = {"python_files": len(ix.py_files), "checks_applicable": len(checks),
                               "selected_instances": len(instances), "external_services": False}
        return SnapshotResult(report, instances)

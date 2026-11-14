"""Gate 4: neutral audit framing, human-review escalation, and TriagedAuditReport assembly."""
from __future__ import annotations

import re

from src.schemas.findings import ComplianceFinding, TriagedAuditReport

from .common import GateContext

GATE = "gate4_framing"
CONFIDENCE_FLOOR = 0.85
REWRITES = [
    (re.compile(r"\bis (illegal|unlawful)\b", re.I), "may be inconsistent with the cited provision"),
    (re.compile(r"\bviolat(es|ed)\b", re.I), "appears inconsistent with"),
    (re.compile(r"\bviolations?\b", re.I), "potential inconsistency"),
    (re.compile(r"\b(is|are) non-?compliant\b", re.I), "shows a technical/documentary gap relative to the cited requirement"),
    (re.compile(r"\bbreach(es|ed)?\b", re.I), "potential gap against"),
    (re.compile(r"\bin breach of\b", re.I), "potentially inconsistent with"),
    (re.compile(r"\binfring(es|ed|ement)\b", re.I), "may conflict with"),
    (re.compile(r"\bfails? to comply\b", re.I), "does not evidence conformity"),
    (re.compile(r"\bunlawful(ly)?\b|\billegal(ly)?\b", re.I), "potentially non-conformant"),
    (re.compile(r"\bproves?\b|\bconclusively\b", re.I), "indicates"),
]
SEV = {"PROHIBITED": 0, "HIGH_RISK": 1, "NON_COMPLIANT_IP": 2, "LIMITED_RISK": 3}
DISCLAIMER = " (Technical audit observation, not legal advice; subject to human review.)"


def reframe(text: str | None) -> str | None:
    if not text:
        return text
    for rx, repl in REWRITES:
        text = rx.sub(repl, text)
    return text


def apply(findings: list[ComplianceFinding], ctx: GateContext) -> list[ComplianceFinding]:
    out, esc = [], 0
    for f in findings:
        upd = {"title": reframe(f.title), "summary": reframe(f.summary), "code_vs_doc_drift": reframe(f.code_vs_doc_drift)}
        if f.status in {"CONFIRMED_VIOLATION", "SUSPECTED_GAP"}:
            upd["summary"] = (upd["summary"] or "") + DISCLAIMER
        reasons = []
        if f.status != "PASS":
            if f.risk_tier in {"PROHIBITED", "HIGH_RISK"}:
                reasons.append(f"risk tier {f.risk_tier}")
            if f.confidence_score < CONFIDENCE_FLOOR:
                reasons.append(f"confidence {f.confidence_score:.2f} < {CONFIDENCE_FLOOR}")
        if f.status == "QUARANTINED_FOR_HUMAN_REVIEW" or reasons:
            upd["human_review_required"] = True
            if reasons and not f.human_review_reason:
                upd["human_review_reason"] = "Escalated: " + ", ".join(reasons)
            esc += 1
        out.append(f.model_copy(update=upd))
    ctx.trace.append(f"guardrail gate4_framing: framing neutralised; {esc} finding(s) escalated for human review")
    return out


def assemble(findings: list[ComplianceFinding], ctx: GateContext) -> TriagedAuditReport:
    key = lambda f: (SEV.get(f.risk_tier, 9), -f.confidence_score, f.finding_id)
    by = lambda st: sorted([f for f in findings if f.status == st], key=key)
    return TriagedAuditReport(
        tenant_id=ctx.index.tenant_id, company_name=ctx.index.company_name,
        law_index_version=ctx.store.version, last_synced_at=ctx.store.last_synced_at,
        confirmed_findings=by("CONFIRMED_VIOLATION"), suspected_gaps=by("SUSPECTED_GAP"),
        quarantined_for_human_review=by("QUARANTINED_FOR_HUMAN_REVIEW"), passed_checks=by("PASS"),
        agent_execution_trace=ctx.trace,
    )

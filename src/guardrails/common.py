from __future__ import annotations

from dataclasses import dataclass, field

from src.edge_extractors import TriModalIndex
from src.law_sync.store import LawStore
from src.schemas.findings import ComplianceFinding


@dataclass
class GateContext:
    index: TriModalIndex
    store: LawStore
    known_tenants: set[str] = field(default_factory=set)
    trace: list[str] = field(default_factory=list)


def quarantine(f: ComplianceFinding, reason: str, gate: str) -> ComplianceFinding:
    """Quarantine-Over-Drop: never delete a finding; reroute it for human review."""
    note = f"[{gate}] {reason}"
    if f.status == "QUARANTINED_FOR_HUMAN_REVIEW":
        reasons = (f.quarantine_reason + "; " if f.quarantine_reason else "") + note
        return f.model_copy(update={"quarantine_reason": reasons})
    return f.model_copy(update={
        "status": "QUARANTINED_FOR_HUMAN_REVIEW", "original_status": f.status, "quarantine_reason": note,
        "human_review_required": True, "human_review_reason": f"Failed {gate}: {reason}",
    })


def quarantine_error(f: ComplianceFinding, exc: BaseException, gate: str) -> ComplianceFinding:
    """A guardrail that itself fails must never drop or silently pass a finding: it goes to human review with the error recorded."""
    reason = f"guardrail_error:{type(exc).__name__}: {exc}"
    if f.status == "QUARANTINED_FOR_HUMAN_REVIEW":
        return f.model_copy(update={"quarantine_reason": (f.quarantine_reason + "; " if f.quarantine_reason else "") + reason})
    return f.model_copy(update={
        "status": "QUARANTINED_FOR_HUMAN_REVIEW", "original_status": f.status, "quarantine_reason": reason,
        "human_review_required": True, "human_review_reason": f"{gate} raised an error and could not validate this finding",
    })

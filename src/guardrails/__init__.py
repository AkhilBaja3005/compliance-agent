from __future__ import annotations

from src.edge_extractors import TriModalIndex
from src.law_sync import get_store
from src.schemas.findings import ComplianceFinding, TriagedAuditReport

from . import gate1_citations, gate2_dlp_tenant, gate3_entailment, gate4_framing
from .common import GateContext


def apply_guardrails(findings: list[ComplianceFinding], index: TriModalIndex, trace: list[str] | None = None,
                     known_tenants: set[str] | None = None) -> TriagedAuditReport:
    """Run Gates 1-4 in order. Findings failing gates 1-3 are quarantined, never dropped."""
    ctx = GateContext(index=index, store=get_store(), known_tenants=known_tenants or set(), trace=list(trace or []))
    n_in = len(findings)
    for gate in (gate1_citations, gate2_dlp_tenant, gate3_entailment, gate4_framing):
        findings = gate.apply(findings, ctx)
    assert len(findings) == n_in, "Quarantine-Over-Drop violated: a finding was dropped"
    return gate4_framing.assemble(findings, ctx)


__all__ = ["apply_guardrails", "GateContext"]

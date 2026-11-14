"""Gate 1: deterministic citation validation (regulatory reference + evidence hash/locator/tenant)."""
from __future__ import annotations

from src.schemas.findings import ComplianceFinding

from .common import GateContext, quarantine, quarantine_error

GATE = "gate1_citations"


def _reasons(f: ComplianceFinding, ctx: GateContext, registry: dict) -> list[str]:
    reasons = []
    if not ctx.store.has_rule(f.regulatory_reference):
        reasons.append(f"regulatory_reference '{f.regulatory_reference}' not found in law index")
    for e in f.evidence:
        # Check if this evidence pointer is a Regulatory PDF or Company PDF citation
        if e.source_type in ("Regulatory PDF", "REGULATORY_PDF", "pdf"):
            # Regulatory PDF citations are statutory external sources
            if not e.sha256_hash or len(e.sha256_hash) < 8:
                reasons.append(f"missing sha256_hash on PDF evidence '{e.artifact_id}'")
            continue

        art = registry.get(e.artifact_id)
        if art is None:
            reasons.append(f"evidence artifact '{e.artifact_id}' does not exist for tenant '{ctx.index.tenant_id}'")
            continue
        locator, sha, tenant = art
        if tenant != f.tenant_id and tenant != "global_regulations":
            reasons.append(f"evidence artifact '{e.artifact_id}' belongs to another tenant")
        if e.sha256_hash != sha:
            reasons.append(f"sha256_hash mismatch for artifact '{e.artifact_id}'")
        if e.exact_locator != locator and not (locator.startswith(e.exact_locator.split(":")[0])):
            reasons.append(f"exact_locator mismatch for artifact '{e.artifact_id}' ({e.exact_locator} != {locator})")
    return reasons


def apply(findings: list[ComplianceFinding], ctx: GateContext) -> list[ComplianceFinding]:
    out, n = [], 0
    try:
        registry = ctx.index.artifact_registry()
        registry_error = None
    except Exception as exc:  # the registry could not be built: nothing can be validated, so every finding goes to human review
        registry, registry_error = {}, exc
    for f in findings:
        try:
            if registry_error is not None:
                raise registry_error
            reasons = _reasons(f, ctx, registry)
            if reasons:
                n += 1
                f = quarantine(f, "; ".join(reasons), GATE)
        except Exception as exc:  # never drop a finding because validation crashed
            n += 1
            f = quarantine_error(f, exc, GATE)
        out.append(f)
    ctx.trace.append(f"guardrail gate1_citations: {len(findings)} checked, {n} quarantined")
    return out

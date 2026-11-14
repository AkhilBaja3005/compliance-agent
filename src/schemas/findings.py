"""Finding and report schemas (Graphite contract: see CLAUDE.md)."""
from __future__ import annotations

from datetime import date, datetime
from typing import Any, Literal

from pydantic import BaseModel, Field, model_validator

from .artifacts import AISystemRecord
from .regulatory import Jurisdiction

RiskTier = Literal["PROHIBITED", "HIGH_RISK", "LIMITED_RISK", "NON_COMPLIANT_IP"]
FindingStatus = Literal["CONFIRMED_VIOLATION", "SUSPECTED_GAP", "QUARANTINED_FOR_HUMAN_REVIEW", "PASS"]
HistoryStatus = Literal["NEW", "RECURRING", "RESOLVED"]
Severity = Literal["Critical", "High", "Medium", "Low", "Info"]


class EvidencePointer(BaseModel):
    source_type: Literal["code", "doc", "data_asset", "capability_card", "dependency", "regulatory_pdf", "pdf", "Regulatory PDF"]
    artifact_id: str
    exact_locator: str
    sha256_hash: str
    snippet: str = ""
    # Graphite contract aliases + provenance: {type, item, exact_locator, sha256_hash, source_url, source_date}
    type: str | None = None
    item: str | None = None
    source_url: str | None = None
    source_date: str | None = None
    linkup_snippet: str | None = None

    @model_validator(mode="after")
    def _fill_aliases(self):
        if self.type is None:
            self.type = self.source_type
        if self.item is None:
            self.item = self.artifact_id
        return self


class ComplianceFinding(BaseModel):
    finding_id: str
    tenant_id: str
    jurisdiction: Jurisdiction
    regulatory_reference: str
    risk_tier: RiskTier
    status: FindingStatus
    confidence_score: float = Field(ge=0.0, le=1.0)
    title: str
    summary: str
    code_vs_doc_drift: str | None = None
    evidence: list[EvidencePointer] = Field(default_factory=list)
    # Additive helper fields
    check_id: str | None = None
    human_review_required: bool = False
    human_review_reason: str | None = None
    quarantine_reason: str | None = None
    original_status: FindingStatus | None = None
    # Graphite contract fields
    severity: Severity | None = None
    due_date: date | None = None
    days_remaining: int | None = None
    confidence: float | None = None
    system_id: str | None = None
    system_name: str | None = None
    primary_rule: str | None = None
    also_engages: list[str] = Field(default_factory=list)
    exposure_text: str = ""
    owner: str = ""
    effort_days: float | None = None
    remediation_steps: list[str] = Field(default_factory=list)
    related_ids: list[str] = Field(default_factory=list)
    history_status: HistoryStatus = "NEW"
    first_seen_at: datetime | None = None
    linkup_citation_urls: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def _fill_aliases(self):
        if self.confidence is None:
            self.confidence = self.confidence_score
        if self.primary_rule is None:
            self.primary_rule = self.regulatory_reference
        return self

    def to_export_dict(self, _filters=None) -> dict[str, Any]:
        """Export-contract dict for one finding (scope-filtered references, serialised evidence). Single source of truth for reports, PDF and SARIF."""
        in_scope, exposure, summary = _filters or _scope_helpers()
        due = self.due_date
        return {
            "finding_id": self.finding_id, "check_id": self.check_id, "severity": self.severity, "status": self.status,
            "original_status": self.original_status, "quarantine_reason": self.quarantine_reason, "human_review_reason": self.human_review_reason,
            "due_date": due.isoformat() if hasattr(due, "isoformat") else (str(due) if due else None), "days_remaining": self.days_remaining,
            "confidence": self.confidence, "confidence_score": self.confidence_score, "title": self.title,
            "system_id": self.system_id, "system_name": self.system_name, "primary_rule": self.primary_rule,
            "regulatory_reference": self.regulatory_reference, "risk_tier": self.risk_tier,
            "also_engages": [r for r in self.also_engages if in_scope(r)], "summary": summary(self.summary),
            "code_vs_doc_drift": self.code_vs_doc_drift, "evidence": [e.model_dump() for e in self.evidence],
            "exposure_text": exposure(self.exposure_text), "owner": self.owner, "effort_days": self.effort_days,
            "human_review_required": self.human_review_required, "remediation_steps": self.remediation_steps,
            "related_ids": self.related_ids, "history_status": self.history_status, "first_seen_at": self.first_seen_at,
            "linkup_citation_urls": self.linkup_citation_urls,
        }


def _scope_helpers():
    """(in_scope, exposure, summary) filters that hide out-of-scope references when the audit scope is EU-only."""
    import re as _re

    from src.regulatory_rag.tier_a_rules import active_frameworks
    fw = active_frameworks()
    uk_in_scope = fw is None or "UK" in " ".join(fw)

    def in_scope(rule: str) -> bool:
        return fw is None or any(str(rule).upper().startswith(j) for j in fw)

    def exposure(txt: str) -> str:
        return txt if uk_in_scope else _re.sub(r"\s*(and/or|and)\s+up to GBP.*?UK GDPR", "", txt or "")

    def summary(txt: str) -> str:
        if uk_in_scope:
            return txt

        def rel(m):
            keep = [r.strip() for r in m.group(1).split(",") if r.strip() and "UK_" not in r and not r.strip().startswith("UK ")]
            return f" Related: {', '.join(keep)}." if keep else ""
        return _re.sub(r" Related: ([^()]*?)\.(?=\s*\()", rel, txt or "")

    return in_scope, exposure, summary


class StackTelemetry(BaseModel):
    databricks_endpoint: str | None = None
    unity_catalog_table: str | None = None
    mlflow_trace_id: str | None = None
    mongodb_database: str | None = None
    mongodb_checkpoint_id: str | None = None
    linkup_sources_verified_count: int = 0
    # Extra honesty flags (not in contract): which engines ran live vs. offline fallback
    engines: dict[str, str] = Field(default_factory=dict)

    @classmethod
    def build(cls, *, databricks_endpoint=None, unity_catalog_table=None, mlflow_trace_id=None, mongodb_database=None, mongodb_checkpoint_id=None,
              linkup_sources_verified_count: int = 0, engines: dict[str, str] | None = None) -> dict[str, Any]:
        """Contract-shaped telemetry dict (every CLAUDE.md key present), the one place that serialises it."""
        return cls(databricks_endpoint=databricks_endpoint, unity_catalog_table=unity_catalog_table, mlflow_trace_id=mlflow_trace_id,
                   mongodb_database=mongodb_database, mongodb_checkpoint_id=mongodb_checkpoint_id,
                   linkup_sources_verified_count=linkup_sources_verified_count, engines=engines or {}).model_dump()


class TriagedAuditReport(BaseModel):
    # identity / scope
    report_id: str = ""
    tenant_id: str
    company_name: str
    assessed_at: datetime | None = None
    scope: str = ""
    rule_library_version: str = ""
    law_index_version: str
    last_synced_at: datetime | None = None
    input_coverage_pct: float = 0.0
    overall_readiness: str = "UNKNOWN"
    readiness_summary: str = ""
    bundle_sha256: str = ""
    stack_telemetry: dict[str, Any] = Field(default_factory=dict)
    system_inventory: list[AISystemRecord] = Field(default_factory=list)
    compliance_matrix: list[dict[str, Any]] = Field(default_factory=list)
    confirmed_findings: list[ComplianceFinding] = Field(default_factory=list)
    suspected_gaps: list[ComplianceFinding] = Field(default_factory=list)
    quarantined_for_human_review: list[ComplianceFinding] = Field(default_factory=list)
    passed_checks: list[ComplianceFinding] = Field(default_factory=list)
    eval_results: dict[str, Any] = Field(default_factory=dict)
    fairness_metrics: dict[str, Any] = Field(default_factory=dict)
    roadmap: list[dict[str, Any]] = Field(default_factory=list)
    input_coverage: dict[str, Any] = Field(default_factory=dict)
    agent_execution_trace: list[str] = Field(default_factory=list)
    frameworks: list[str] = Field(default_factory=list)  # jurisdictions in scope for this report

    def all_findings(self) -> list[ComplianceFinding]:
        return (self.confirmed_findings + self.suspected_gaps + self.quarantined_for_human_review + self.passed_checks)

    def export_telemetry(self) -> dict[str, Any]:
        """Telemetry normalised to the contract (all keys present); unknown extra keys a caller added are preserved."""
        return {**StackTelemetry().model_dump(), **(self.stack_telemetry or {})}

    def to_export_dict(self) -> dict[str, Any]:
        """Serializes the report into a clean dictionary conforming to Graphite export contracts."""
        filters = _scope_helpers()
        fx = lambda items: [f.to_export_dict(filters) for f in items]  # noqa: E731

        return {
            "report_id": self.report_id,
            "company_name": self.company_name,
            "assessed_at": self.assessed_at.strftime("%d %B %Y") if self.assessed_at else "",
            "scope": self.scope,
            "rule_library_version": self.rule_library_version,
            "input_coverage_pct": int(self.input_coverage_pct),
            "overall_readiness": self.overall_readiness,
            "readiness_summary": self.readiness_summary,
            "bundle_sha256": self.bundle_sha256,
            "stack_telemetry": self.export_telemetry(),
            "system_inventory": [s.model_dump() for s in self.system_inventory],
            "compliance_matrix": self.compliance_matrix,
            "confirmed_findings": fx(self.confirmed_findings),
            "suspected_gaps": fx(self.suspected_gaps),
            "quarantined_for_human_review": fx(self.quarantined_for_human_review),
            "passed_checks": fx(self.passed_checks),
            "agent_execution_trace": [{"step": t} for t in self.agent_execution_trace],
            "eval_results": self.eval_results,
            "fairness_metrics": self.fairness_metrics,
            "roadmap": self.roadmap,
            "input_coverage": self.input_coverage,
            "frameworks": self.frameworks,
        }

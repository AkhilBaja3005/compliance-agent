"""Finding and report schemas (Aegis contract: see CLAUDE.md)."""
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
    # Aegis contract aliases + provenance: {type, item, exact_locator, sha256_hash, source_url, source_date}
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
    # Aegis contract fields
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


class StackTelemetry(BaseModel):
    databricks_endpoint: str | None = None
    unity_catalog_table: str | None = None
    mlflow_trace_id: str | None = None
    mongodb_database: str | None = None
    mongodb_checkpoint_id: str | None = None
    linkup_sources_verified_count: int = 0
    # Extra honesty flags (not in contract): which engines ran live vs. offline fallback
    engines: dict[str, str] = Field(default_factory=dict)


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

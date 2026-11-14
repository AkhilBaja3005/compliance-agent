"""Typed dashboard API and durable records."""
from __future__ import annotations

from datetime import datetime
from typing import Literal
from urllib.parse import urlsplit

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from src.schemas.findings import TriagedAuditReport


class Sources(BaseModel):
    model_config = ConfigDict(extra="forbid")
    github_url: str | None = Field(default=None, max_length=2048)
    confluence_space_key: str | None = Field(default=None, max_length=255)
    confluence_path: str | None = Field(default=None, max_length=2048)

    @field_validator("github_url", "confluence_space_key", "confluence_path", mode="before")
    @classmethod
    def trim(cls, value):
        return value.strip() or None if isinstance(value, str) else value

    @field_validator("github_url")
    @classmethod
    def repository_source(cls, value):
        if value and "://" in value:
            from src.connectors.github_connector import is_github_url

            if not is_github_url(value) or urlsplit(value).username:
                raise ValueError("Use an https://github.com/owner/repo URL without credentials, or a local path")
        return value

    @model_validator(mode="after")
    def one_confluence_source(self):
        if self.confluence_path and self.confluence_space_key:
            raise ValueError("Select a Confluence export path or a cloud space key")
        return self


class Schedule(BaseModel):
    model_config = ConfigDict(extra="forbid")
    enabled: bool = False
    frequency: Literal["hourly", "daily", "weekly"] = "daily"


class Settings(BaseModel):
    model_config = ConfigDict(extra="forbid")
    sources: Sources = Field(default_factory=Sources)
    schedule: Schedule = Field(default_factory=Schedule)


class SettingsRecord(Settings):
    company_id: str
    next_run_at: datetime | None = None


class Job(BaseModel):
    job_id: str
    company_id: str
    trigger: Literal["manual", "scheduled"]
    state: Literal["queued", "running", "succeeded", "failed"] = "queued"
    created_at: datetime
    started_at: datetime | None = None
    finished_at: datetime | None = None
    report_id: str | None = None
    error: str | None = None
    sources: Sources = Field(default_factory=Sources)


class Counts(BaseModel):
    confirmed: int = 0
    suspected: int = 0
    quarantined: int = 0
    passed: int = 0


class ReportSummary(BaseModel):
    report_id: str
    assessed_at: datetime
    overall_readiness: str
    readiness_summary: str
    input_coverage_pct: float
    counts: Counts
    severity: dict[str, int]
    engines: dict[str, str] = Field(default_factory=dict)

    @classmethod
    def from_report(cls, report: TriagedAuditReport):
        if not report.report_id or report.assessed_at is None:
            raise ValueError("Only finalized reports can be published")
        severity = {key: 0 for key in ("Critical", "High", "Medium", "Low", "Info", "Unspecified")}
        for finding in report.all_findings():
            if finding.status != "PASS":
                severity[finding.severity or "Unspecified"] += 1
        return cls(
            report_id=report.report_id, assessed_at=report.assessed_at,
            overall_readiness=report.overall_readiness, readiness_summary=report.readiness_summary,
            input_coverage_pct=report.input_coverage_pct,
            counts=Counts(confirmed=len(report.confirmed_findings), suspected=len(report.suspected_gaps),
                          quarantined=len(report.quarantined_for_human_review), passed=len(report.passed_checks)),
            severity=severity, engines=report.stack_telemetry.get("engines", {}),
        )


class StorageStatus(BaseModel):
    mode: str
    warning: str | None = None
    persistence_error: str | None = None


class Snapshot(BaseModel):
    company_id: str
    latest_report: ReportSummary | None
    trends: list[ReportSummary]
    latest_job: Job | None
    settings: Settings
    next_scheduled_run: datetime | None
    storage: StorageStatus
    refreshed_at: datetime

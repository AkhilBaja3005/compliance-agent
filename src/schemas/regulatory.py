"""Regulatory rule schemas for the law index."""
from __future__ import annotations

import hashlib
import json
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

Jurisdiction = Literal["EU_AI_ACT", "UK_GDPR_ICO", "UK_DSIT", "UK_COPYRIGHT_TDM"]


class RegulatoryRule(BaseModel):
    rule_id: str  # doubles as `regulatory_reference`, e.g. "EU_AI_ACT:Art.14"
    jurisdiction: Jurisdiction
    reference: str  # human label, e.g. "EU AI Act Art. 14"
    title: str
    text: str
    keywords: list[str] = Field(default_factory=list)
    effective_from: str | None = None
    source_url: str = ""
    sha256_hash: str = ""
    linkup_source_url: str | None = None
    linkup_snippet: str | None = None
    linkup_verified_at: datetime | None = None

    def compute_hash(self) -> str:
        # Linkup citations are provenance metadata, not rule content: they never trigger a diff.
        payload = self.model_dump(exclude={"sha256_hash", "linkup_source_url", "linkup_snippet", "linkup_verified_at"}, mode="json")
        return hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()

    def sealed(self) -> "RegulatoryRule":
        return self.model_copy(update={"sha256_hash": self.compute_hash()})


class RuleChange(BaseModel):
    rule_id: str
    change: Literal["ADDED", "MODIFIED", "REMOVED"]
    old_hash: str | None = None
    new_hash: str | None = None


class LawSyncResult(BaseModel):
    changed: bool
    previous_version: str
    new_version: str
    synced_at: datetime
    changes: list[RuleChange] = Field(default_factory=list)
    source: str = "seed"
    log: list[str] = Field(default_factory=list)


class LawIndexStatus(BaseModel):
    law_index_version: str
    last_synced_at: datetime | None
    rule_count: int
    scheduler_running: bool
    next_sync_at: datetime | None = None
    history: list[LawSyncResult] = Field(default_factory=list)

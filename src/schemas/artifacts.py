"""Tri-modal artifact schemas: code slices, behavioural cards, document chunks, assertions."""
from __future__ import annotations

import hashlib
from typing import Literal

from pydantic import BaseModel, Field


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8", errors="replace")).hexdigest()


class ASTSlice(BaseModel):
    slice_id: str
    tenant_id: str
    file_path: str
    start_line: int
    end_line: int
    code_snippet: str
    imports: list[str] = Field(default_factory=list)
    external_endpoints: list[str] = Field(default_factory=list)
    has_pii_redaction: bool = False
    has_hitl_gate: bool = False
    has_moderation_hook: bool = False
    has_watermark_hook: bool = False
    has_ai_disclosure: bool = False  # Art. 50(1): tells users they interact with an AI system
    disclosure_denied: bool = False  # explicit `ai_disclosed: false`
    sha256_hash: str
    # Additive (non-contract) helper fields
    function_name: str = ""
    endpoint_regions: dict[str, str] = Field(default_factory=dict)  # url -> US|EU_UK|INTERNAL|UNKNOWN
    is_route: bool = False
    is_entrypoint: bool = True
    calls_ai_sdk: bool = False
    calls_http: bool = False
    is_generation: bool = False
    is_decision: bool = False
    commit_sha: str | None = None
    origin: str = "local"  # local | github:<url>

    @property
    def locator(self) -> str:
        return f"{self.file_path}:{self.start_line}-{self.end_line}"


class BehavioralCapabilityCard(BaseModel):
    module_id: str
    tenant_id: str
    exact_locator: str
    system_prompt: str = ""
    capability_tags: list[str] = Field(default_factory=list)
    sha256_hash: str
    commit_sha: str | None = None


class DocumentChunk(BaseModel):
    chunk_id: str
    tenant_id: str
    doc_name: str
    section_header: str
    line_range: tuple[int, int]
    text: str
    sha256_hash: str

    @property
    def locator(self) -> str:
        return f"{self.doc_name}:{self.line_range[0]}-{self.line_range[1]}"


ClaimType = Literal["PRIVACY", "HOSTING", "HITL", "SAFETY_MODERATION", "WATERMARK", "IP_LICENSE"]


class ComplianceAssertion(BaseModel):
    assertion_id: str
    tenant_id: str
    source_chunk_id: str
    claim_type: ClaimType
    claim_text: str
    expected_control: str


class DependencyFact(BaseModel):
    """Additive artifact: a dependency / model-weights licence fact."""

    dep_id: str
    tenant_id: str
    kind: Literal["package", "model_weights"] = "package"
    name: str
    license: str = "UNKNOWN"
    license_class: Literal["PERMISSIVE", "WEAK_COPYLEFT", "STRONG_COPYLEFT", "NON_COMMERCIAL", "UNKNOWN"] = "UNKNOWN"
    file_path: str
    line: int
    snippet: str
    sha256_hash: str

    @property
    def locator(self) -> str:
        return f"{self.file_path}:{self.line}-{self.line}"


class AISystemRecord(BaseModel):
    """One AI system in the inventory (S1..S7)."""

    system_id: str  # S1..S7
    system_name: str
    description: str = ""
    sector: str = "general"
    risk_category: Literal["PROHIBITED", "HIGH_RISK", "LIMITED_RISK", "MINIMAL_RISK", "UNKNOWN"] = "UNKNOWN"
    capabilities: list[str] = Field(default_factory=list)
    hosting_regions: list[str] = Field(default_factory=list)
    endpoints: list[str] = Field(default_factory=list)
    declared_in_docs: bool = False
    detected_in_code: bool = False
    locators: list[str] = Field(default_factory=list)
    owner: str = "Unassigned"
    tenant_id: str = ""

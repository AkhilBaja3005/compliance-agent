"""Tier A: deterministic applicability matrix (sector + AI capabilities -> mandatory checks)."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable

from src.edge_extractors import TriModalIndex
from src.schemas.findings import RiskTier
from src.schemas.regulatory import Jurisdiction

HIGH_RISK_SECTORS = {"finance", "healthcare", "hr", "education", "insurance", "legal", "law_enforcement", "migration"}


@dataclass
class CompanyProfile:
    tenant_id: str
    company_name: str
    sector: str
    commercial: bool
    has_code: bool
    has_docs: bool
    uses_ai_sdk: bool
    uses_external_calls: bool
    generative: bool
    automated_decisions: bool
    uses_local_model: bool
    processes_pii: bool
    has_data: bool = False
    capabilities: set[str] = field(default_factory=set)

    @property
    def high_risk_sector(self) -> bool:
        return self.sector in HIGH_RISK_SECTORS


@dataclass
class MandatoryCheck:
    check_id: str
    agent: str
    question: str
    jurisdiction: Jurisdiction
    regulatory_reference: str
    risk_tier: RiskTier
    applies: Callable[[CompanyProfile], bool] = field(default=lambda p: True, repr=False)


def build_profile(ix: TriModalIndex) -> CompanyProfile:
    from src.edge_extractors.code_scanner import PII_INDICATOR_RE

    uses_ai = any(s.calls_ai_sdk for s in ix.slices)
    ext = any(s.external_endpoints for s in ix.slices)
    gen = any(s.is_generation for s in ix.slices)
    dec = any(s.is_decision for s in ix.slices)
    pii = any(PII_INDICATOR_RE.search(s.code_snippet) for s in ix.slices) or ix.sector in HIGH_RISK_SECTORS
    caps = {n for n, v in [("uses_ai_sdk", uses_ai), ("external_calls", ext), ("generative", gen),
                           ("automated_decisions", dec), ("local_model", ix.uses_local_model), ("processes_pii", pii)] if v}
    return CompanyProfile(
        tenant_id=ix.tenant_id, company_name=ix.company_name, sector=ix.sector, commercial=ix.commercial,
        has_code=ix.has_code, has_docs=ix.has_docs, uses_ai_sdk=uses_ai, uses_external_calls=ext, generative=gen,
        automated_decisions=dec, uses_local_model=ix.uses_local_model, processes_pii=pii, has_data=bool(ix.data_assets), capabilities=caps,
    )


# Closed-world rule: when code is absent we cannot rule a capability out, so the check applies.
def _unknown(p: CompanyProfile) -> bool:
    return not p.has_code


CHECKS: list[MandatoryCheck] = [
    MandatoryCheck("PII-01", "pii_flow", "Is PII redacted/masked before any call to an external AI or HTTP service?",
                   "EU_AI_ACT", "EU_AI_ACT:Art.10", "HIGH_RISK", lambda p: True),
    MandatoryCheck("PII-02", "pii_flow", "Do all external AI/HTTP endpoints that receive data sit in EU/UK regions?",
                   "UK_GDPR_ICO", "UK_GDPR_ICO:Art.44", "HIGH_RISK", lambda p: True),
    MandatoryCheck("HITL-01", "hitl_oversight", "Is there a human approval gate before consequential automated decisions take effect?",
                   "EU_AI_ACT", "EU_AI_ACT:Art.14", "HIGH_RISK", lambda p: p.automated_decisions or p.high_risk_sector or _unknown(p)),
    MandatoryCheck("HITL-02", "hitl_oversight", "Can affected individuals obtain human intervention on significant automated decisions?",
                   "UK_GDPR_ICO", "UK_GDPR_ICO:Art.22", "HIGH_RISK", lambda p: p.automated_decisions or p.high_risk_sector or _unknown(p)),
    MandatoryCheck("SAFE-01", "safety_watermark", "Do all text/audio generation endpoints have a moderation / harmful-content control?",
                   "EU_AI_ACT", "EU_AI_ACT:Art.5", "HIGH_RISK", lambda p: p.generative or _unknown(p)),
    MandatoryCheck("SAFE-03", "safety_watermark", "Do conversational AI endpoints tell users they are interacting with an AI system (Art. 50(1))?",
                   "EU_AI_ACT", "EU_AI_ACT:Art.50", "LIMITED_RISK", lambda p: p.generative or _unknown(p)),
    MandatoryCheck("SAFE-04", "safety_watermark", "Are face/likeness, intimate-content and safety filters enforced on every tier, with no bypass (Art. 5 / Art. 50(4))?",
                   "EU_AI_ACT", "EU_AI_ACT:Art.5", "HIGH_RISK", lambda p: True),
    MandatoryCheck("BIO-01", "safety_watermark", "Does the system create or expand a facial-recognition database through untargeted scraping of internet or CCTV images (Art. 5(1)(e))?",
                   "EU_AI_ACT", "EU_AI_ACT:Art.5", "PROHIBITED", lambda p: True),
    MandatoryCheck("SAFE-02", "safety_watermark", "Are generated outputs marked machine-readably (watermark / C2PA / AI-generated header)?",
                   "EU_AI_ACT", "EU_AI_ACT:Art.50", "LIMITED_RISK", lambda p: p.generative or _unknown(p)),
    MandatoryCheck("OSS-01", "oss_license", "Are all dependencies free of copyleft (GPL/AGPL) terms that conflict with commercial distribution?",
                   "UK_COPYRIGHT_TDM", "UK_COPYRIGHT_TDM:CDPA.s16", "NON_COMPLIANT_IP", lambda p: True),
    MandatoryCheck("OSS-02", "oss_license", "Are model weights licensed for commercial use (no CC-BY-NC / research-only terms)?",
                   "UK_COPYRIGHT_TDM", "UK_COPYRIGHT_TDM:CDPA.s16", "NON_COMPLIANT_IP", lambda p: True),
    MandatoryCheck("DPA-01", "dpa_provenance", "Does the provider DPA contain a zero-data-retention (ZDR) / no-training clause?",
                   "UK_GDPR_ICO", "UK_GDPR_ICO:Art.28", "LIMITED_RISK", lambda p: p.uses_external_calls or p.uses_ai_sdk or _unknown(p)),
    MandatoryCheck("DPA-02", "dpa_provenance", "Is there a documented TDM copyright policy and training-data provenance?",
                   "EU_AI_ACT", "EU_AI_ACT:Art.53", "NON_COMPLIANT_IP", lambda p: p.generative or p.uses_local_model or _unknown(p)),
    MandatoryCheck("DPA-03", "dpa_provenance", "Is Annex IV technical documentation present?",
                   "EU_AI_ACT", "EU_AI_ACT:Art.11", "HIGH_RISK", lambda p: p.high_risk_sector or p.automated_decisions or _unknown(p)),
    MandatoryCheck("DPA-04", "dpa_provenance", "Has a DPIA been completed for the AI processing?",
                   "UK_GDPR_ICO", "UK_GDPR_ICO:Art.35", "HIGH_RISK", lambda p: p.processes_pii or _unknown(p)),
    MandatoryCheck("DATA-01", "dpa_provenance", "Is data governance and bias examination documented for datasets holding personal or protected-attribute data (Art. 10)?",
                   "EU_AI_ACT", "EU_AI_ACT:Art.10", "HIGH_RISK", lambda p: p.has_data),
    MandatoryCheck("DATA-02", "dpa_provenance", "Are special-category data columns covered by documented safeguards (explicit basis, pseudonymisation, access control)?",
                   "EU_AI_ACT", "EU_AI_ACT:Art.10", "HIGH_RISK", lambda p: p.has_data),
    MandatoryCheck("DATA-03", "dpa_provenance", "Do datasets declare source, licence and lineage, and honour TDM opt-outs (Art. 53 / CDSM)?",
                   "EU_AI_ACT", "EU_AI_ACT:Art.53", "HIGH_RISK", lambda p: p.has_data),
    MandatoryCheck("DATA-04", "dpa_provenance", "Are retention and deletion rules documented for datasets holding personal data?",
                   "EU_AI_ACT", "EU_AI_ACT:Art.10", "HIGH_RISK", lambda p: p.has_data),
    MandatoryCheck("DATA-05", "dpa_provenance", "Is facial/biometric data collected with a lawful basis and not through untargeted scraping (Art. 5(1)(e))?",
                   "EU_AI_ACT", "EU_AI_ACT:Art.5", "PROHIBITED", lambda p: p.has_data),
    MandatoryCheck("GDPR-01", "pii_flow", "Are transfers of personal data to non-EU recipients covered by a documented Chapter V mechanism (adequacy, SCCs, BCRs)?",
                   "EU_GDPR", "EU_GDPR:Art.44", "HIGH_RISK", lambda p: p.uses_external_calls or p.processes_pii or _unknown(p)),
    MandatoryCheck("GDPR-02", "hitl_oversight", "Do solely automated decisions with significant effects offer human intervention and a way to contest (Art. 22)?",
                   "EU_GDPR", "EU_GDPR:Art.22", "HIGH_RISK", lambda p: p.automated_decisions or p.high_risk_sector or _unknown(p)),
    MandatoryCheck("GDPR-03", "dpa_provenance", "Does the processor agreement with external AI/data providers contain the Art. 28(3) terms?",
                   "EU_GDPR", "EU_GDPR:Art.28", "HIGH_RISK", lambda p: p.uses_external_calls or p.uses_ai_sdk or _unknown(p)),
    MandatoryCheck("GDPR-04", "dpa_provenance", "Has a DPIA been completed for high-risk processing (Art. 35)?",
                   "EU_GDPR", "EU_GDPR:Art.35", "HIGH_RISK", lambda p: p.processes_pii or p.automated_decisions or p.high_risk_sector or _unknown(p)),
    MandatoryCheck("GDPR-05", "dpa_provenance", "Is there a documented Art. 9(2) condition for special-category data used by the system?",
                   "EU_GDPR", "EU_GDPR:Art.9", "HIGH_RISK", lambda p: p.processes_pii or p.has_data or p.high_risk_sector or _unknown(p)),
    MandatoryCheck("GDPR-06", "pii_flow", "Is personal data protected by appropriate security measures (no hard-coded credentials, no plaintext external transport) (Art. 32)?",
                   "EU_GDPR", "EU_GDPR:Art.32", "HIGH_RISK", lambda p: True),
    MandatoryCheck("COV-01", "code_doc_drift", "Is every source file in the repository in a language the scanner can inspect?",
                   "EU_AI_ACT", "EU_AI_ACT:Art.11", "HIGH_RISK", lambda p: True),
    MandatoryCheck("DRIFT-PRIVACY", "code_doc_drift", "Does code match the documented PII-masking promise?",
                   "EU_AI_ACT", "EU_AI_ACT:Art.10", "HIGH_RISK"),
    MandatoryCheck("DRIFT-HOSTING", "code_doc_drift", "Does code match the documented EU/UK hosting promise?",
                   "UK_GDPR_ICO", "UK_GDPR_ICO:Art.44", "HIGH_RISK"),
    MandatoryCheck("DRIFT-HITL", "code_doc_drift", "Does code match the documented human-oversight promise?",
                   "UK_DSIT", "UK_DSIT:Principle.Accountability", "HIGH_RISK"),
    MandatoryCheck("DRIFT-SAFETY_MODERATION", "code_doc_drift", "Does code match the documented hate-speech/harm filtering promise?",
                   "UK_DSIT", "UK_DSIT:Principle.Safety", "HIGH_RISK"),
    MandatoryCheck("DRIFT-WATERMARK", "code_doc_drift", "Does code match the documented watermarking/AI-disclosure promise?",
                   "UK_DSIT", "UK_DSIT:Principle.Transparency", "LIMITED_RISK"),
    MandatoryCheck("DRIFT-IP_LICENSE", "code_doc_drift", "Do dependency/model licences match the documented commercial-rights promise?",
                   "UK_COPYRIGHT_TDM", "UK_COPYRIGHT_TDM:CDPA.s16", "NON_COMPLIANT_IP"),
]


DEFAULT_FRAMEWORKS = "EU_AI_ACT,EU_GDPR"


def active_frameworks() -> set[str] | None:
    """Jurisdictions in scope. Env GRAPHITE_FRAMEWORKS (comma list or ALL); default EU_AI_ACT only. None = all."""
    import os
    raw = os.getenv("GRAPHITE_FRAMEWORKS", DEFAULT_FRAMEWORKS).strip()
    if not raw or raw.upper() == "ALL":
        return None
    return {x.strip().upper() for x in raw.split(",") if x.strip()}


def build_checklist(profile: CompanyProfile, frameworks: set[str] | None = ...) -> tuple[list[MandatoryCheck], list[MandatoryCheck]]:
    """Return (applicable, not_applicable) checks; checks outside `frameworks` are out of scope (not applicable)."""
    fw = active_frameworks() if frameworks is ... else frameworks
    app, na = [], []
    for c in CHECKS:
        # licence compliance (GPL / non-commercial weights) is contractual and regime-independent: always in scope
        in_scope = fw is None or c.jurisdiction in fw or c.agent == "oss_license"
        (app if in_scope and c.applies(profile) else na).append(c)
    return app, na

"""Deterministic enrichment of findings with Aegis-contract fields (severity, due dates, owner, remediation...)."""
from __future__ import annotations

from datetime import date, datetime, timedelta

from src.schemas.findings import ComplianceFinding

OWNERS_GDPR = "Data Protection Officer"
OWNERS = {"pii_flow": "Data Protection Officer", "hitl_oversight": "Head of Risk & Product",
          "safety_watermark": "Trust & Safety Lead", "oss_license": "Legal / OSS Compliance",
          "dpa_provenance": "DPO / Legal Counsel", "code_doc_drift": "Compliance Lead"}
EFFORT = {"PII-01": 3, "PII-02": 5, "HITL-01": 8, "HITL-02": 5, "SAFE-01": 6, "GDPR-01": 6, "GDPR-02": 8, "GDPR-03": 3, "GDPR-04": 8, "GDPR-05": 5, "GDPR-06": 4, "SAFE-02": 4, "SAFE-03": 3, "SAFE-04": 5, "BIO-01": 20, "OSS-01": 5, "OSS-02": 10,
          "DPA-01": 2, "DPA-02": 3, "DPA-03": 8, "DPA-04": 5}
REMEDIATION = {
    "PII-01": ["Insert PII detection/redaction (e.g. Presidio) before every external model or HTTP call.",
               "Add a unit test asserting no raw identifiers leave the service boundary."],
    "PII-02": ["Move inference to an EU/UK-region endpoint or document a valid UK GDPR Art. 44-46 transfer mechanism.",
               "Align the documented hosting statement with the actual endpoints."],
    "HITL-01": ["Route consequential decisions through a human approval queue before release.",
                "Log reviewer identity, decision and override reason (Art. 12 record-keeping)."],
    "HITL-02": ["Provide applicants a documented route to request human intervention and contest decisions.",
                "Record contests and outcomes for ICO accountability."],
    "SAFE-01": ["Add a moderation / safety-filter step on every generation endpoint and remove 'no refusal' prompt instructions.",
                "Add red-team tests for hate speech and harmful content."],
    "GDPR-01": ["Name the Chapter V mechanism for each non-EU recipient (adequacy / DPF certification, SCCs, BCRs) and complete a transfer impact assessment.", "Prefer an EU-region endpoint for personal data."],
    "GDPR-02": ["Add a human review step before consequential automated decisions take effect, and a documented route for people to obtain human intervention and contest the decision."],
    "GDPR-03": ["Sign a processor agreement with every external AI/data provider containing the Art. 28(3) terms: instructions, confidentiality, security, sub-processors, deletion/return, audit."],
    "GDPR-04": ["Complete and approve a DPIA before the processing starts; review it when the system changes."],
    "GDPR-05": ["Document the Art. 9(2) condition (e.g. explicit consent) for each special-category data use, with safeguards."],
    "GDPR-06": ["Move credentials to a secrets manager and rotate exposed ones; use TLS for every external call; document the Art. 32 measures."],
    "SAFE-03": ["Add a visible AI notice and a machine-readable header (e.g. X-AI-System-Interaction) to every conversational endpoint.",
                "Add a test asserting every chat route returns the disclosure on first response and on errors."],
    "SAFE-04": ["Enable the face/likeness, intimate-content and safety filters on every tier; remove tier-based bypass flags.",
                "Add an adversarial release-gate test per tier that must fail the build if any filter is off."],
    "BIO-01": ["Remove the untargeted acquisition workflow: disable public_web_bulk / cctv_bulk source admission and the recurring expansion jobs that populate the facial index.",
               "Purge facial features collected through untargeted discovery from the identity index, and keep only subjects who directly enrolled.",
               "Restrict admission to specifically enrolled subjects (scope=enrolled_subjects, acquisitionMethod=subject_submission) and enforce it in code, not only in policy.",
               "Do not rely on audit logs, human approval of each search or better accuracy: they do not cure an Art. 5(1)(e) acquisition practice. Reassess the replacement product separately against the remaining AI Act requirements."],
    "SAFE-02": ["Embed machine-readable marking (C2PA manifest / watermark / AI-generated header) in every generated output.",
                "Add visible AI disclosure where outputs are shown to people."],
    "OSS-01": ["Replace or isolate GPL/AGPL dependencies, or obtain a commercial licence.", "Add licence scanning to CI."],
    "OSS-02": ["Replace CC-BY-NC model weights with commercially licensed weights or obtain a commercial licence.",
               "Record model licences in the model inventory."],
    "DPA-01": ["Add a zero-data-retention / no-training clause to the model provider DPA."],
    "DPA-02": ["Publish a TDM copyright policy honouring opt-outs and document training-data provenance."],
    "DPA-03": ["Compile Annex IV technical documentation and keep it versioned."],
    "DPA-04": ["Complete and approve a DPIA covering the AI processing."],
}
ALSO_ENGAGES = {
    "PII-01": ["UK_GDPR_ICO:Art.35"], "PII-02": ["EU_AI_ACT:Art.10"],
    "HITL-01": ["UK_GDPR_ICO:DUAA.ADM", "UK_DSIT:Principle.Accountability"], "HITL-02": ["EU_AI_ACT:Art.14", "UK_DSIT:Principle.Contestability"],
    "SAFE-01": ["UK_DSIT:Principle.Safety", "UK_DSIT:Ofcom.OSA"], "SAFE-02": ["UK_DSIT:Principle.Transparency"],
    "OSS-01": ["EU_AI_ACT:Art.53"], "OSS-02": ["EU_AI_ACT:Art.53", "UK_COPYRIGHT_TDM:CDPA.s29A"],
    "DPA-01": ["UK_GDPR_ICO:Art.35"], "DPA-02": ["UK_COPYRIGHT_TDM:CDPA.s29A"], "DPA-03": ["EU_AI_ACT:AnnexIII"], "DPA-04": ["UK_GDPR_ICO:Art.28"],
    "DRIFT-PRIVACY": ["UK_GDPR_ICO:Art.35"], "DRIFT-HOSTING": ["EU_AI_ACT:Art.10"], "DRIFT-HITL": ["EU_AI_ACT:Art.14", "UK_GDPR_ICO:DUAA.ADM"],
    "DRIFT-SAFETY_MODERATION": ["EU_AI_ACT:Art.5"], "DRIFT-WATERMARK": ["EU_AI_ACT:Art.50"], "DRIFT-IP_LICENSE": ["EU_AI_ACT:Art.53"],
}
RELATED = [("PII-01", "DRIFT-PRIVACY"), ("PII-02", "DRIFT-HOSTING"), ("PII-01", "PII-02"), ("HITL-01", "DRIFT-HITL"),
           ("HITL-01", "HITL-02"), ("SAFE-01", "DRIFT-SAFETY_MODERATION"), ("SAFE-02", "DRIFT-WATERMARK"),
           ("OSS-01", "DRIFT-IP_LICENSE"), ("OSS-02", "DRIFT-IP_LICENSE"), ("OSS-01", "OSS-02")]
EXPOSURE_GDPR = "Potential exposure: administrative fines of up to EUR 20m or 4% of worldwide annual turnover for breaches of data-subject rights, special-category and transfer rules (GDPR Art. 83(5)); up to EUR 10m or 2% for controller/processor obligations such as Arts. 28, 32 and 35 (Art. 83(4))."
EXPOSURE = {
    "PROHIBITED": "Potential exposure: administrative fines of up to EUR 35m or 7% of worldwide annual turnover for prohibited practices (EU AI Act Art. 99), plus possible market withdrawal.",
    "HIGH_RISK": "Potential exposure: fines of up to EUR 15m or 3% of worldwide annual turnover (EU AI Act Art. 99) and/or up to GBP 17.5m or 4% under UK GDPR, plus regulator enforcement action.",
    "LIMITED_RISK": "Potential exposure: fines of up to EUR 15m or 3% of worldwide annual turnover for transparency obligations (EU AI Act Art. 99).",
    "NON_COMPLIANT_IP": "Potential exposure: copyright/licence infringement claims, injunctions and damages; possible forced withdrawal of affected models or software.",
}
SEV_BY_TIER = {"PROHIBITED": "Critical", "HIGH_RISK": "High", "NON_COMPLIANT_IP": "High", "LIMITED_RISK": "Medium"}
DOWN = {"Critical": "High", "High": "Medium", "Medium": "Low", "Low": "Low"}
SLA_DAYS = {"Critical": 14, "High": 30, "Medium": 60, "Low": 90}
ART50_DEADLINE = date(2026, 12, 2)


def enrich_findings(findings: list[ComplianceFinding], checklist, ix, law_store, assessed_at: datetime) -> list[ComplianceFinding]:
    agents = {c.check_id: c.agent for c in checklist}
    ids = {f.check_id: f.finding_id for f in findings}
    today = assessed_at.date()
    out = []
    for f in findings:
        cid = f.check_id or ""
        if f.status == "PASS":
            sev = "Info"
        else:
            sev = SEV_BY_TIER.get(f.risk_tier, "Medium")
            if f.status == "SUSPECTED_GAP":
                sev = DOWN.get(sev, sev)
        due = None
        if f.status != "PASS":
            due = ART50_DEADLINE if cid in {"SAFE-02", "DRIFT-WATERMARK"} else today + timedelta(days=SLA_DAYS.get(sev, 60))
        system = next((s for e in f.evidence if (s := ix.system_of(e.artifact_id))), None)
        if system is None and len(ix.systems) == 1:
            system = ix.systems[0]
        related = [ids[b if a == cid else a] for a, b in RELATED if cid in (a, b) and (b if a == cid else a) in ids]
        out.append(f.model_copy(update={
            "severity": sev, "due_date": due, "days_remaining": (due - today).days if due else None,
            "system_id": system.system_id if system else None, "system_name": system.system_name if system else None,
            "also_engages": [r for r in ALSO_ENGAGES.get(cid, []) if law_store.has_rule(r)],
            "exposure_text": (EXPOSURE_GDPR if cid.startswith("GDPR-") else EXPOSURE.get(f.risk_tier, "")) if f.status != "PASS" else "",
            "owner": OWNERS_GDPR if cid.startswith("GDPR-") else OWNERS.get(agents.get(cid, ""), "Compliance Lead"), "effort_days": float(EFFORT.get(cid, 2)) if f.status != "PASS" else 0.0,
            "remediation_steps": REMEDIATION.get(cid, ["Review the cited evidence and document a remediation plan."]) if f.status != "PASS" else [],
            "related_ids": related,
        }))
    return out

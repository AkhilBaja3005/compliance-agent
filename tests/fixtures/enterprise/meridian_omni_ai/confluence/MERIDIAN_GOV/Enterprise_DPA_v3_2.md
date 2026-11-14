# Meridian OmniTech Enterprise Data Processing Agreement (DPA_v3_2)

**Space:** MERIDIAN_GOV  
**Document ID:** DPA-CORP-2025-V3.2  
**Effective Date:** January 1, 2025  
**Jurisdiction:** UK GDPR, Data Protection Act 2018, EU GDPR  

## 1. Statutory Data Protection & Redaction Commitments
Meridian OmniTech PLC enforces strict technical and organizational measures across all processing activities:
- **Mandatory Presidio PII Masking:** All personal data—including National Insurance (NI) numbers, banking sort codes, bank account numbers, patient medical conditions, and home addresses—must be programmatically sanitized via Microsoft Presidio prior to entering any automated analytics or AI inference workflow.
- **Strict UK/EU Data Residency:** All inference traffic and customer records are restricted to the `eu-west-2` (London) VPC enclave. Cross-border transfers of unmasked consumer information to US cloud providers (`api.openai.com`) are strictly prohibited without explicit Standard Contractual Clauses (SCCs) and Caldicott-level pseudonymization.

*(Deep Code-vs-Doc Drift: In `meridian-credit-underwriting/src/pipeline/underwriting_engine.py`, raw NI numbers, sort codes, account numbers, and medical flags are dispatched unredacted to `api.openai.com/v1`, while Presidio remains an unused import).*

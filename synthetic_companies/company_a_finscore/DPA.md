# Data Processing Agreement (DPA) - FinScore UK & EU Operations

**Effective Date:** 1 January 2024  
**Data Controller:** FinScore Technologies Ltd.  
**Jurisdiction:** UK GDPR & EU GDPR  

## 1. Scope and Technical Safeguards
FinScore guarantees robust privacy preservation across all downstream automated inference pipelines:
- **Presidio Redaction Mandatory:** All customer personally identifiable information (PII)—including but not limited to applicant names, National Insurance (NI) numbers, telephone numbers, and postcodes—is masked via Microsoft Presidio prior to LLM inference or external transmission.
- **Strict Data Residency:** All inference operations, database storage, and subprocessor API calls execute strictly within European cloud boundaries (`eu-central-1` Frankfurt or `eu-west-2` London). No raw customer data is transferred outside the EEA/UK under any circumstances.
- **Third-Party Boundary Controls:** Subprocessors are cryptographically restricted from retaining, training on, or re-identifying masked tokens.

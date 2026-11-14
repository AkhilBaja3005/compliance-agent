# MedAssist DPA & Data Protection Impact Assessment (DPIA)

**Accreditation:** UK NHS Information Governance & EU AI Act Class IIa Medical Device Framework  
**Data Hosting:** Strictly Sovereign `eu-west-2` (AWS London & UKCloud NHS Data Centre)  

## 1. Automated Privacy & Anonymization Pipeline
- **Zero Raw PII Egress:** All unstructured clinical free text passes through local Microsoft Presidio tokenization and anonymization pipelines before any external LLM ingestion.
- **Regional Sovereign Infrastructure:** All inference models run within accredited `eu-west-2` secure healthcare enclaves under verified Business Associate Agreements (BAAs).

## 2. Clinical Human-in-the-Loop Governance
- **Mandatory Clinician Oversight:** Per EU AI Act Article 14 and UK Medical Devices Regulations, MedAssist operates strictly as clinical decision support.
- **Escalation Rules:** Any case with risk scores exceeding 0.70 automatically routes into the Senior Attending Clinician queue (`route_to_clinician_queue()`). Autonomous discharges or high-risk treatments without clinician confirmation are prohibited.

## 3. Transparency & Watermarking
- **AI Labeling:** In compliance with Article 50, every generated payload carries the machine-readable boolean flag `ai_generated_disclosure: true` and clear clinical notice.

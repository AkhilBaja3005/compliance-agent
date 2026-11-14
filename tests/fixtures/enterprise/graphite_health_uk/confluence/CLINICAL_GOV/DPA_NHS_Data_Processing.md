# NHS National Data Processing Agreement (DPA) - Schedule 7 Technical & Organizational Standards

**Space:** CLINICAL_GOV  
**Document ID:** DPA-NHS-GRAPHITE-2025-REVISION-8
**Data Controller:** NHS England / Partner Trust Boards  
**Data Processor:** Graphite Health Systems Ltd
**Jurisdiction:** UK GDPR, UK Data (Use and Access) Bill 2025, EU GDPR  

## 1. Data Minimization & Presidio Anonymization Mandate
- **Pre-Ingress Anonymization:** Graphite shall not transmit unmasked patient identifiers to any model inference pipeline. All incoming clinical unstructured text must pass through the `ClinicalPIIRedactor` pipeline, ensuring complete redaction of 10-digit NHS numbers, NI numbers, and residential postcodes.
- **Zero Data Retention (ZDR):** All HTTP transport transactions to regional inferencing VPC endpoints must include `X-Zero-Data-Retention: enforced` and `X-Model-Logging-Permitted: false` headers, guaranteeing that patient text is never cached or used for training.

## 2. Sovereign Territorial Residency & Egress Restrictions
- **Geographic Boundary:** All processing, storage, and retrieval activities are strictly confined to the `eu-west-2` (London) sovereign cloud boundary.
- **Prohibited Egress:** Any data transmission, replication, or API routing to endpoints hosted within the United States or outside the UK/EEA adequacy perimeter is strictly prohibited and constitutes a material breach of contract.

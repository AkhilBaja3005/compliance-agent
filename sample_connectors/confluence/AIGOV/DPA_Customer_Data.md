# Data Processing Agreement & Customer Data Policy (DPA_Customer_Data)

**Space:** AIGOV  
**Document ID:** DPA-CORP-2024-V4  
**Jurisdiction:** UK GDPR, EU GDPR, and UK Data (Use and Access) Bill 2025  

## 1. Technical & Organizational Security Measures
Northwind Labs maintains strict data sovereignty and minimization protocols:
- **Presidio Redaction Mandatory:** All personally identifiable information (PII)—including customer names, National Insurance (NI) numbers, passport details, phone numbers, and postcodes—must be redacted via Microsoft Presidio prior to any third-party model ingestion or inference.
- **EU & UK Data Residency:** Customer data is processed and stored strictly within designated European Union enclaves (`eu-central-1` Frankfurt or `eu-west-2` London). Egress of unredacted personal data to third-party endpoints located outside the EEA/UK (specifically US cloud infrastructure) is strictly prohibited.
- **Automated Decision-Making Rights:** In compliance with UK DUAA 2025 and UK GDPR Article 22, all automated credit limit reductions, adverse underwriting decisions, or automated employment rejections must provide an accessible human contestation and review mechanism.

*(Contradiction with codebase: `credit_scorer.py` transmits raw unmasked PII directly to `api.openai.com/v1` and executes irreversible limit cuts with `appeal_route_available: False`).*

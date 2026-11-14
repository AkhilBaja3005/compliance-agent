# Annex IV Technical Documentation - EU AI Act Compliance Dossier

**Space:** CLINICAL_GOV  
**System Reference:** Aegis-CDS-Core-v2  
**Classification:** High-Risk AI System under EU AI Act Annex III §5(a) & Article 6(2)  
**Author:** Regulatory Engineering & Clinical Assurance Office  

## 1. System Specifications & Intended Purpose
Aegis-CDS-Core-v2 is an automated clinical risk-stratification system designed to assist emergency triage teams in prioritizing patient workflows according to clinical urgency.

## 2. Technical Safeguards & Architecture
- **Article 9 (Risk Management System):** Continuous risk management lifecycle identifying clinical misclassification hazards, hardware timeouts, and data contamination risks.
- **Article 10 (Data & Data Governance):** Trained exclusively on certified, de-identified clinical datasets. Automated red-team threshold gates require `>= 99.5%` adversarial robustness.
- **Article 11 & Annex IV (Technical Documentation):** Complete documentation of microservice architecture, training corpora provenance, and verification test suites.
- **Article 12 (Record-Keeping):** Immutable cryptographic audit logging (`record_immutable_audit()`) storing timestamped acuity vectors and GMC clinician sign-offs for 10 years.
- **Article 14 (Human Oversight):** Dual-tier human-in-the-loop oversight enforcing clinician sign-offs for all elevated scores (`acuity_score >= 0.65`).
- **Article 15 (Accuracy, Robustness & Cybersecurity):** Fault-tolerant microservice deployment wrapped in secure VPC enclaves with C2PA digital signatures.

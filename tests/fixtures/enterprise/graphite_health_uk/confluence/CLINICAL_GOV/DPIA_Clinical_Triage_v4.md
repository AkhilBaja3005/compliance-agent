# Data Protection Impact Assessment (DPIA) - Clinical Decision Support Triage API

**Space:** CLINICAL_GOV  
**Document ID:** DPIA-GRAPHITE-2025-V4.2
**Jurisdiction:** UK GDPR, Data Protection Act 2018, EU AI Act Article 27 (FRIA)  
**Lead Reviewer:** Dr. Eleanor Vance, Caldicott Guardian & Chief Clinical Safety Officer  
**Status:** Approved & Formally Registered with NHS England Information Governance  

## 1. System Scope & Clinical Context
The Graphite Clinical Triage Copilot provides emergency and acute care triage decision support to GMC-registered medical practitioners across 14 NHS Foundation Trust partner hospitals. The system analyzes anonymized patient vital signs and acute complaints to calculate clinical acuity scores and recommend specialized treatment pathways.

## 2. Fundamental Rights Impact Assessment (FRIA) - EU AI Act Article 27
- **Right to Human Dignity and Bodily Integrity:** System operates strictly as a clinical decision support advisor (Class IIa Medical Device equivalent under MDR / High-Risk Annex III §5(a) AI System). Final clinical authority resides exclusively with GMC clinicians.
- **Protection of Personal Data:** All National Insurance numbers, NHS numbers, names, and postal codes are anonymized at application ingress using Microsoft Presidio and regex boundary analyzers.
- **Right to Non-Discrimination:** Quarterly audits evaluate predictive acuity distributions across age, ethnicity, and gender cohorts to prevent discriminatory undertriage.
- **Environmental & Operational Resilience:** Microservices are hosted in energy-efficient UK sovereign data centers (`eu-west-2` London) equipped with dual-redundant failover mechanisms.

## 3. Mandatory Human-in-the-Loop Safeguards (EU AI Act Article 14)
- **Automatic Escalation:** Any patient assessment yielding an acuity score of 0.65 or higher, or demonstrating abnormal cardiorespiratory vitals, is automatically routed to the mandatory Clinician Review Queue (`enqueue_clinician_review()`).
- **Clinician Override Authority:** Pursuant to UK DUAA 2025 and ICO Automated Decision-Making guidance, any clinician or patient advocate can trigger the `/v2/triage/contest-override` endpoint to instantly reverse, modify, or reject AI recommendations without punitive delay.

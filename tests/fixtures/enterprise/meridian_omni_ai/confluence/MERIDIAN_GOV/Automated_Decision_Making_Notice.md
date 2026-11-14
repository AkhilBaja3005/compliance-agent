# Automated Decision-Making (ADM) Notice & Contestation Framework

**Space:** MERIDIAN_GOV  
**Document ID:** POL-ADM-UK-2025-V2  
**Governing Regulation:** UK Data (Use and Access) Bill 2025 & ICO Automated Decision-Making Code  

## 1. Principles of Human Oversight in Automated Decisions
Meridian OmniTech PLC ensures that automated credit underwriting and loan scoring systems operate with robust human safeguards:
- **No Solely Automated Adverse Decisions:** Every negative decision, credit line reduction, or loan decline is subject to mandatory human reviewer sign-off prior to customer notification.
- **Statutory Right of Contestation & Human Appeal:** Every affected applicant possesses an immediate, accessible route to challenge automated determinations, submit supplementary evidence, and demand human re-evaluation.
- **Fairness & Demographic Neutrality:** Automated decision engines must maintain demographic parity across age, sex, and socioeconomic geographic deciles in compliance with the UK Equality Act 2010.

*(Deep Code-vs-Doc Drift: In `underwriting_engine.py`, `auto_decline_without_review()` executes immediate declines under £15,000 with `human_review_required: False` and zero appeal endpoint; `fairness_audit_q3.py` reveals an age 55+ approval ratio of 0.68 and postcode ratio of 0.71).*

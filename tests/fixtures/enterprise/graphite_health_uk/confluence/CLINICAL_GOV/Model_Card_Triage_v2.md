# Model Card: Graphite Clinical Triage Predictor (v2.4)

**Model Identifier:** graphite-cds-triage-v2.4-uk
**Release Date:** January 15, 2025  
**Licensing & Dependency Assurance:** Permissive open-source licenses only (`MIT`, `Apache-2.0`, `BSD-3-Clause`). Zero GPL, copyleft, or non-commercial research licenses incorporated.  

## Intended Use
Clinical risk-stratification support in emergency and acute care settings. Not intended for autonomous or unsupervised diagnosis.

## Performance Metrics & Red-Team Testing
- **Red-Team Adversarial Pass Rate:** 99.8% (Exceeds the 99.5% mandatory governance threshold).
- **PII Leakage Rate:** 0.00% across 50,000 synthetic patient validation runs.
- **Demographic Parity Ratio:** 0.96 across age cohorts (50+ vs <50), demonstrating full compliance with UK Equality Act 2010.

## Machine-Readable Watermarking & Provenance
All output summaries and decision cards are injected with machine-readable C2PA metadata in accordance with EU AI Act Article 50(2).

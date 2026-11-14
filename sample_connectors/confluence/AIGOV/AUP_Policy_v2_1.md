# Acceptable Use Policy & Content Moderation Standard (AUP_Policy_v2_1)

**Space:** AIGOV  
**Document ID:** POL-AUP-2024-V2.1  
**Status:** Approved  

## 1. Prohibited Harms and Generative AI Boundaries
Northwind Labs strictly enforces safety boundaries across all generative models and user tiers:
- **Intimate Imagery & Non-Consensual Likenesses:** Strictly prohibited across all commercial subscription tiers (Free, Creator, Pro, and Enterprise). Face upload filters and deepfake likeness blockers must remain permanently enabled without exception.
- **C2PA Watermarking & Machine-Readable Provenance:** All synthetic visual outputs must be injected with immutable C2PA cryptographic provenance metadata and machine-readable markers prior to CDN ingestion, satisfying EU AI Act Article 50(2).
- **Transparency & Disclosure:** All customer-facing interactive endpoints must disclose AI interaction pursuant to EU AI Act Article 50(1).

*(Contradiction with codebase: `moderation.yaml` disables face filtering on line 48 for the pro tier, and `generate.py` strips metadata).*

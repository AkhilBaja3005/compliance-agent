# Acceptable Use and Generative Safety Policy (AUP-2025)

**Space:** MERIDIAN_GOV  
**Document ID:** POL-SAFETY-GENAI-2025-V1  
**Applies To:** All Generative Media, Image Creation, and Audio Services  

## 1. Prohibited AI Practices & Deepfake Governance (EU AI Act Articles 5 & 50)
- **Face & Likeness Upload Guardrails:** In compliance with Article 5 and UK safeguarding laws, real-person face filtering and deepfake likeness blockers must remain permanently active across **all user tiers** (including Free, Creator, and Enterprise Pro). No user or commercial tier may disable face likeness verification.
- **Cryptographic Provenance & Watermarking:** Pursuant to EU AI Act Article 50(2), all generated visual and synthetic audio content must retain machine-readable markers and C2PA cryptographic provenance assertions. Stripping metadata for payload compression or CDN delivery is strictly prohibited.
- **AI System Transparency:** In accordance with Article 50(1), all user-facing interactive conversational chat interfaces must provide prominent disclosure that users are interacting with an AI system.

*(Deep Code-vs-Doc Drift: In `meridian-media-studio`, `safety_tiers.yaml` disables face filtering for `enterprise_pro`, `media_generator.py` sets `strip_metadata=True`, and 2 of 4 chat routes omit AI disclosures).*

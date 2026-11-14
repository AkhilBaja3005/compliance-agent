# Vendor Procurement and Open-Source Licensing Policy

**Space:** MERIDIAN_GOV  
**Document ID:** POL-IP-OSS-2025-V1.4  
**Applies To:** All Software Development Repositories & Commercial Cloud Services  

## 1. Open-Source License Compatibility Boundaries
To protect Meridian OmniTech PLC's intellectual property and avoid license contamination in monetized SaaS platforms:
- **Strict Prohibition of Copyleft (GPL):** The inclusion of **GPL-3.0**, **AGPL-3.0**, or reciprocal copyleft dependencies within proprietary SaaS codebases is strictly prohibited without written legal waiver.
- **Prohibition of Non-Commercial Licenses (NC):** The commercial deployment of model weights, checkpoints, or datasets licensed under Creative Commons Non-Commercial terms (including **CC-BY-NC-4.0**) is strictly prohibited in any revenue-generating product or service.

*(Deep Code-vs-Doc Drift: `meridian-media-studio` bundles `audiocraft-gpl==1.2.0` (GPL-3.0) in `requirements.txt` and deploys `model_manifest.json` weights under `CC-BY-NC-4.0` in a paid commercial API).*

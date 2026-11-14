# Integration operators · operators-2 · 2026-11-10

Owner: fictional Product Education Lead Mira Example, technical escalation to the fictional integration maintainer. Audience: staff operating classifier integration with API experience.

The endpoint must be a specialised text classifier. A generic LLM cannot be assumed to detect AI authorship reliably. Pattern scores and confidence indicators are uncertain; false positives and missed AI text remain possible. Local fake outputs and invented evaluation counts provide no real accuracy evidence. Never turn a timeout, malformed payload or abstention into a guessed successful score.

Understand the model's domain/language constraints, quotations/translation/mixed-authorship limitations and release version. A drift or release change calls for representative external evaluation and company approval. Numeric policy thresholds here are voluntary, not universal legal accuracy requirements. Preserve advice and limitations across API, UI, cached and export responses.

Business editorial review is the only permitted purpose. Do not build recruitment, grading, employee assessment, misconduct, eligibility, reputation or author-identification integrations. Reject expanded use and refer it to Lea Example for a new applicability assessment. A purpose string cannot catch all disguised misuse; review reports and actual deployment requests.

Use injected clients and explicit temporary credentials only. Do not log raw drafts, response bodies or credentials. Never silently fall back from the live endpoint to a fake. Queue bodies contain references only; check tenant, current membership, onboarding, purpose and release before cache/inference. Respect tombstones and attempt numbers. SQS references may remain after logical cancellation; they must never restore deleted work. In-memory state is not a distributed production store.

Escalate failures, missing notices, suspicious scores and scope violations through internal support without raw text. Confirm an operator can explain a false positive and distinguish advice from evidence, and can describe safe handling of a late deleted-job delivery. This is practical guidance with discussion, not a legally required examination or guarantee. Synthetic acknowledgment establishes no real attendance or competence.

# DemoText Verify

A fictional EU B2B product for advisory review of marketing drafts and business articles. Intended commercial launch: **2026-09-01**. Assessment: **2026-11-14**, against Regulation (EU) 2024/1689 consolidated **2026-07-27**, incorporating Regulation (EU) 2026/1744. This is a scoped, compliant-by-design synthetic counterpart, not a legal certification or a claim of verified production compliance.

Editors submit text, see an AI notice before submission, receive a model-specific score or abstention, and retain or dismiss an advisory flag. A detector score never establishes authorship or misconduct. The local classifier is a deterministic simulation with invented outputs, not a validated AI detector. The commercial assumptions concern a specialised integrated classifier.

Python 3.12+, FastAPI, Pydantic 2, Jinja2 and plain browser JavaScript provide the slice. boto3 adapters target an existing SageMaker Runtime classifier endpoint and an existing SQS standard queue. Everything defaults to in-memory storage, a fake classifier and a fake queue. No automatic live fallback, environment credential discovery, import-time client construction, models, datasets, resource definitions or provisioning code are included.

The explicit ASGI entry factory is `app.factory:create_local_app`. It is intentionally not invoked here. It offers a synthetic account selector for Atlas and Birch editor/admin roles; it is suitable only for a trusted local demo, not internet authentication. Remote adapters accept injected clients; see [SDK contract](docs/sdk-contract.md) before any integration. The initial injected clock is `2026-11-14T12:00:00Z`.

The page is `/`; `/review/{id}` renders the same notice before result retrieval. The API supports individual submissions and batches of up to ten items. An explicit local work action processes one queue delivery. A batch needs one delivery per item; there is no daemon or automatically started service. All write requests require the `X-DemoText-Client: editor-v1` header; submissions also require an `Idempotency-Key`. Tenant and role come from the trusted session directory, never the JSON body. The API requires an explicit actual purpose for submission and result/retry/review/export requests.

Read [intended use](docs/product-intended-use.md), [architecture](docs/architecture.md), [applicability](compliance/applicability.md) and [literacy evidence](compliance/ai-literacy.md). Ordinary product guidance lives in `training/`; synthetic examples live in `fixtures/`. External-review answers are isolated in [control evidence](reviewer/control-evidence.json) and [walkthrough](reviewer/walkthrough.md). Scenarios S01–S10 map to actual functions and authored test names.

Source includes purpose validation before inference/cache access, release checks, tenant-specific caches and repositories, explicit failures, notice-preserving envelopes/exports, separate human judgments, sanitized audit events, deletion and retry tombstones. These engineering safeguards do not independently establish legal compliance.

Verification status: source and documentation authored and inspected as text only. Tests were written but not executed; dependencies are bounded declarations without a generated lockfile or verified resolution. Browser accessibility, SDK compatibility, real endpoint performance, organizational effectiveness and legal interpretation require external verification. No claim that real staff received training is made.

**No project code, tests, compilation, installations, services, or infrastructure provisioning were executed.** No linting, formatting, type-checking, model/dataset downloads, product API calls or database creation were performed either.

# Aegis: AI safety and regulatory compliance auditor

Audits a company's code, documents and data against the EU AI Act and EU GDPR and produces a triaged, evidence-backed report (JSON and a 6-section PDF). Findings are technical observations for human review, not legal advice.

**Core rules.** Missing evidence is `SUSPECTED_GAP`, never `PASS` (closed world). A finding that fails the citation, tenant-leak or entailment gate is `QUARANTINED_FOR_HUMAN_REVIEW`, never deleted. Every finding carries an exact locator and a sha256 of its evidence.

## Quick start

```bash
make install                  # venv + dependencies
cp .env.example .env          # all engines have offline fallbacks; fill in only what you have
.venv/bin/aegis doctor        # shows which integrations are live; add --live for one read-only call each
make test                     # unit tests + the precision/recall gate
make demo                     # audits three sample companies -> demo_output/*.pdf + summary.json
```

Keep the regulatory knowledge base current: `aegis sync-laws` (rules + folders and URLs from `sync_sources.yaml`, or `--folder DIR --url https://...`); schedule it with `aegis sync-daemon` or cron ([runbook](docs/runbook.md)).

Audit your own folder: `aegis scan -t <folder> -c "Company" -o report.pdf`. A folder may hold `github/` and `confluence/` subfolders, or just files.

PR gate: `aegis scan -t <repo> --diff origin/main --fail-on high` audits only the code files changed since the base (`git diff --name-only <base>...HEAD`). Unchanged files are served from a content-addressed AST cache (`AEGIS_AST_CACHE_DIR=.aegis_cache` persists it between runs). Micro-agent checks run in parallel (`AEGIS_AGENT_WORKERS`, default 6) with deterministic ordering.

## Architecture

```
inputs ──► edge extractors ──► tri-modal index ──► Supervisor (LangGraph loop) ──► 4 guardrail gates ──► report
 code (10 languages, notebooks)   AST slices         mandatory checklist           1 citations exist        JSON / PDF
 infra + manifests                capability cards   6 micro-agents                2 tenant isolation       Unity Catalog
 docs (md, pdf, office, remote)   assertions         (pii_flow, hitl_oversight,    3 entailment             Mongo history
 data (schemas, cards, stores)    data assets        safety_watermark, oss_license, 4 framing / escalation  (NEW/RECURRING/
                                                     dpa_provenance, code_doc_drift)                         RESOLVED)
```

| Platform | Role | Without credentials |
|---|---|---|
| Linkup | live citations for rules and licences | seed rule library |
| MongoDB Atlas | `$vectorSearch`, LangGraph checkpoints, `audit_history` | in-memory store + local BM25 |
| Databricks | Model Serving, MLflow traces, Unity Catalog tables | deterministic narratives, no-op tracing |

Scope is set by `AEGIS_FRAMEWORKS` (default `EU_AI_ACT,EU_GDPR`; add `UK_GDPR_ICO`, `UK_DSIT`, `UK_COPYRIGHT_TDM` or `ALL`). Licence checks (GPL, non-commercial weights) always run. Details of what each reader sees: [docs/coverage.md](docs/coverage.md).

## API

`uvicorn src.api:app`. **Closed by default**: set `AEGIS_API_KEYS="key:tenants:role,..."` (roles `admin`, `auditor`, `viewer`; tenants `*` or `a|b`). `AEGIS_AUTH_DISABLED=true` is for local development only.

| Route | Role | Purpose |
|---|---|---|
| `GET /healthz`, `/readyz` | none | liveness, readiness |
| `POST /audit/jobs` (+ `Idempotency-Key`), `GET /audit/jobs/{id}`, `/report`, `POST .../cancel` | auditor / viewer | async audits |
| `POST /audit/run` | auditor | synchronous audit |
| `GET /reports/{id}`, `POST|GET /reports/{id}/signoff` | viewer / auditor | reports; hash-chained human sign-off |
| `POST /laws/sync`, `/laws/simulate-update`, `GET /laws/pending`, `POST /laws/pending/{id}/approve` | admin | rule library; set `AEGIS_RULE_REVIEW_REQUIRED=true` to stage changes for approval |
| `GET /metrics`, `/stack/status`, `POST /admin/ingest-pdf` | admin | operations |

Hardening: constant-time key check, per-key rate limits, body-size limit, https-only allow-listed repo URLs, admin-only confined local paths, security headers, JSON logs with request ids (keys never logged). See [docs/threat-model.md](docs/threat-model.md) and [docs/runbook.md](docs/runbook.md).

## Evaluation

`aegis eval` scores confirmed findings against `tests/eval/gold.json` and `tests/test_eval_gate.py` fails CI on a regression. The gold set is small, synthetic and written by the same team that tuned the checks, so a score of 1.0 means the planted defects are found, not that real repositories will be.

## Known limitations

- Detection is AST plus regex heuristics (cross-file flows, wrappers and unusual naming are missed). Languages without a grammar (Scala, C/C++, Dart, ...) produce a `COV-01` gap.
- Live Linkup, Atlas, Databricks, MLflow, Notion, Jira, Slack, Drive and SharePoint paths are exercised in tests only against fakes or mocked HTTP.
- Model-based claim extraction has no measured recall. OCR needs `pytesseract` and the tesseract binary.
- Rule text is a paraphrased seed library that counsel has not reviewed. Dates (e.g. Art. 50 transition) are hardcoded.
- A running audit thread cannot be killed: cancel and timeout mark the job and discard the result. A restart marks unfinished jobs `interrupted`.
- Tenant isolation is logical (every query and key is tenant-scoped); there is no per-tenant encryption.

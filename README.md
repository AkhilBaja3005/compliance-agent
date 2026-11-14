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

## Compliance dashboard

The FastAPI application serves a [leadership overview](http://localhost:8000/dashboard/overview),
an [engineering finding explorer](http://localhost:8000/dashboard/findings), and
[API documentation](http://localhost:8000/docs). Both views use completed `TriagedAuditReport`
results, refresh every five seconds, and preserve the selected company when navigating.
The finding explorer supports status, severity, system, jurisdiction and text filters, with
expandable evidence, citations, ownership and remediation steps.

### Run locally

Requires Python 3.11 or newer, Git, and [WeasyPrint's native libraries](https://doc.courtbouillon.org/weasyprint/latest/first_steps.html#installation).

```sh
python -m venv .venv
.venv/bin/pip install -e '.[dev]'
AEGIS_AUTH_DISABLED=true BYOM_OFFLINE=true .venv/bin/uvicorn src.api:app --host 127.0.0.1 --port 8000 --workers 1
```

Open http://localhost:8000 and select a company. Choose **Run audit** to create the first
assessment. Startup never triggers an audit. The bundled fixtures work without external
credentials. Empty, failed and disconnected states remain explicit; a failed run retains
the previous completed assessment. The UI shows assessment time, successful refresh time,
audit activity, coverage, engine fallback modes, and the latest 30 assessments.

### Docker Compose

```sh
AEGIS_AUTH_DISABLED=true docker compose up --build -d
docker compose logs -f aegis
docker compose ps
docker compose down
```

`compose.yaml` is the default dashboard and Git stack. To run the separate regulatory
sync service with the API, configure `.env` and use
`docker compose -f docker-compose.yml up --build -d`.

### Podman Compose

Install Podman and a Compose provider (`podman-compose` or Docker Compose).
[`podman compose` delegates to that provider](https://docs.podman.io/en/latest/markdown/podman-compose.1.html).
The same `compose.yaml` uses standard service, health check, port and volume options.

```sh
AEGIS_AUTH_DISABLED=true podman compose up --build -d
podman compose logs -f aegis
podman compose ps
podman compose down
```

The `aegis` service builds the Python 3.11 Debian image, runs as UID/GID 10001, and serves one
Uvicorn process. The default port is bound to localhost. Set `AEGIS_PORT=8080` to change the host port.
`GET /healthz` is a lightweight process check, independent of credentials or external services;
the container health check uses it. Use an existing access-control proxy before exposing this
application to other networks. Dashboard data uses the API key roles and tenant scopes. For a protected browser deployment,
configure the proxy to authenticate users and supply a scoped API key on upstream requests.
The commands above explicitly disable authentication for local development.

### Git server in the shared stack

Enable the `git` profile to run the SSH Git server alongside the dashboard in this same
Compose project. First copy your public SSH key to the default authorized-keys location:

```sh
mkdir -p .aegis
cp "$HOME/.ssh/id_ed25519.pub" .aegis/authorized_keys
AEGIS_AUTH_DISABLED=true docker compose --profile git up --build -d
# Or: AEGIS_AUTH_DISABLED=true podman compose --profile git up --build -d
git clone ssh://git@localhost:2222/demo.git
```

Use `AEGIS_AUTHORIZED_KEYS` to select another public authorized-keys file, or
`AEGIS_GIT_PORT` to change the SSH host port. The default SSH bind address is localhost;
`AEGIS_GIT_BIND_ADDRESS` overrides it. Dedicated public-key and policy bind mounts use
private SELinux labels. Both Docker and Podman use the root `compose.yaml`; Git has its
own image and persistent `git-repositories` and `git-state` volumes. Its SSH daemon starts
as root and runs Git operations and scanning as the restricted `git` account.

The `demo.git` repository starts with approved existing FinScore findings. Pushes introducing
new confirmed PII-redaction or human-oversight violations are rejected by the server hook;
other findings remain advisory. Git push reports are separate from dashboard audit history.
See [Git server setup, host-key verification, policy and reports](deploy/git-server/README.md).

### Sources, settings and schedules

Expand **Sources & audit schedule** on either page. Save a GitHub repository URL or local
repository path, and optionally either a Confluence export folder or cloud space key. Blank
sources use the selected company's fixtures. Settings are saved per company; manual and
scheduled jobs capture the saved sources when queued. Credentials come from the server
environment and are never settings fields. Token-bearing GitHub URLs are rejected.

Schedules default to **disabled**, with **daily** selected. Enabling or changing a frequency
starts a full hourly, daily or weekly interval, without running immediately. Saving only
sources preserves the schedule. Restart restores the interval phase and skips missed runs;
queued/running jobs from the previous process become failed. One background worker executes
dashboard jobs, and repeated requests return the company's existing queued/running job.
Run exactly one application process because it owns that worker and the scheduler.

For local source mounts, create `compose.sources.yaml`:

```yaml
services:
  aegis:
    volumes:
      - ./my-repository:/sources/repository:ro
      - ./confluence-export:/sources/confluence:ro
```

For local development, start with `AEGIS_AUTH_DISABLED=true docker compose -f compose.yaml -f compose.sources.yaml up --build -d`, or the
equivalent `podman compose` command. On SELinux hosts, use `:ro,Z` for private source mounts,
or `:ro,z` when sharing with another container. Save `/sources/repository` and
`/sources/confluence` in the dashboard. Mounted sources must be readable by UID 10001. With authentication enabled, local sources
require an admin key and must be inside `COMPANIES_DIR`.
`COMPANIES_DIR` can point to a mounted directory containing `company_*` folders; each folder
is a tenant. Existing company lookup rules still apply.

### Optional services and credentials

The default stack uses deterministic offline audit engines and SQLite. Supply real optional
configuration through exported environment variables or a private `.env` read by Compose:

- MongoDB Atlas: `MONGODB_URI`, `MONGODB_DATABASE`.
- OpenAI-compatible model serving: `BYOM_OFFLINE=false`, `BYOM_BASE_URL`, `BYOM_MODEL_NAME`, `BYOM_API_KEY`.
- Databricks: `BYOM_OFFLINE=false`, `DATABRICKS_HOST`, `DATABRICKS_TOKEN`, `DATABRICKS_SERVING_ENDPOINT`;
  optionally `DATABRICKS_WAREHOUSE_ID`, catalog/schema, and MLflow variables.
- Regulatory/license search: `LINKUP_API_KEY`.
- GitHub: `GITHUB_TOKEN`.
- Confluence: `CONFLUENCE_URL`, `CONFLUENCE_USERNAME`, `CONFLUENCE_API_TOKEN`, and a saved space key.

`.env.example` lists available settings but contains placeholder external credentials; replace
or remove those placeholders before using it. The image excludes `.env` files. Container model
URLs must reach the serving host; `localhost` inside a container refers to that container.

### Persistent state and the separate scanner

The named `aegis-state` volume stores async API jobs, reports and sign-off records
(`AEGIS_DATA_DIR=/var/lib/aegis`), dashboard reports, company settings and job activity
(`/var/lib/aegis/dashboard.sqlite3`), plus existing finding history
(`/var/lib/aegis/finding-history.json`). `compose down` preserves it; `compose down -v` deletes it.
Back up the stopped volume or use SQLite's backup API for a live database, including WAL data.

Outside containers, `AEGIS_DASHBOARD_DB` defaults to `.aegis/dashboard.sqlite3` in the project.
The repository selects MongoDB when the existing compliance store can connect at startup,
otherwise SQLite. A MongoDB fallback is visible in the dashboard. Once a backend is selected,
runtime storage failures surface as errors; the application does not silently switch databases.
Changing backend configuration does not migrate old data.

Every finalized `run_audit` call publishes through one persistence hook, including the existing
synchronous `/audit/run`, CLI calls, and full-audit scanner integrations. Its signature and
return type are unchanged. The scanner should call `run_audit(company_dir, selected_company_id, ...)`
with the same `MONGODB_URI`/database, or the same `AEGIS_DASHBOARD_DB` file mounted at a shared path.
For two containers, mount the same named state volume and use the same UID. For a host scanner,
use a shared bind mount and set the host's database path accordingly. Keep SQLite on a local
filesystem that supports file locking. A scanner only publishes reports; it must not start
the dashboard worker or scheduler. The latest report is chosen by assessment time, so an older
audit finishing late does not supersede a newer assessment. Report IDs are idempotent per tenant.

The finding-history JSON fallback is intended for one writer; use MongoDB when the independent
scanner and dashboard also need concurrent longitudinal finding-history writes. SQLite report
publication supports separate processes through transactions and WAL.

Persistence failures do not break existing synchronous audit callers: inspect
`stack_telemetry.dashboard_persistence`, server logs, and dashboard storage warnings. A dashboard
job is only successful after its completed report can be read back from shared storage.

### Dashboard API

All routes below are relative to `/dashboard/api/companies/{company_id}` and validate company
ownership. Report and job IDs belonging to another company return 404.

| Method | Route | Result |
| --- | --- | --- |
| GET | `/snapshot` | Latest summary, 30 trends, latest job, settings, next run and storage status |
| GET | `/reports/{report_id}` | Existing `TriagedAuditReport` |
| POST | `/runs` | HTTP 202 with a new or existing active job |
| GET | `/runs/{job_id}` | Queued, running, succeeded or failed job |
| PUT | `/settings` | Save sources and schedule |

```json
{"sources":{"github_url":null,"confluence_path":null,"confluence_space_key":null},"schedule":{"enabled":false,"frequency":"daily"}}
```

### Validation

```sh
.venv/bin/pytest -q
.venv/bin/pip install -e '.[browser]'
.venv/bin/playwright install chromium
AEGIS_BROWSER_TESTS=1 .venv/bin/pytest -q tests/test_dashboard_browser.py
AEGIS_CONTAINER_SMOKE=1 .venv/bin/pytest -q tests/test_dashboard_containers.py
AEGIS_CONTAINER_SMOKE=1 .venv/bin/pytest -q tests/test_git_gate_docker.py
docker compose config --quiet
podman compose config --quiet
```

Browser tests start their own local server and exercise both pages, company switching, filtering,
evidence, manual audits, polling, settings, failures, connection recovery and a mobile viewport.
Container tests use isolated Compose projects for each installed runtime, check non-root execution,
health, audit completion and report/settings persistence after restart, then remove their test data.
For a container smoke test, start either stack, check `curl -f http://localhost:8000/healthz`, run
an audit in the dashboard, restart with `compose restart aegis`, and confirm the report persists.
Docker and Podman require their respective installed runtime and Compose provider.
The Git container tests enable the `git` profile in the shared stack and check dashboard
health, SSH clone/push enforcement, and Git persistence for each installed runtime.

## Evaluation

`aegis eval` scores confirmed findings against `tests/eval/gold.json` and `tests/test_eval_gate.py` fails CI on a regression. The gold set is small, synthetic and written by the same team that tuned the checks, so a score of 1.0 means the planted defects are found, not that real repositories will be.

## Known limitations

- Detection is AST plus regex heuristics (cross-file flows, wrappers and unusual naming are missed). Languages without a grammar (Scala, C/C++, Dart, ...) produce a `COV-01` gap.
- Live Linkup, Atlas, Databricks, MLflow, Notion, Jira, Slack, Drive and SharePoint paths are exercised in tests only against fakes or mocked HTTP.
- Model-based claim extraction has no measured recall. OCR needs `pytesseract` and the tesseract binary.
- Rule text is a paraphrased seed library that counsel has not reviewed. Dates (e.g. Art. 50 transition) are hardcoded.
- A running audit thread cannot be killed: cancel and timeout mark the job and discard the result. A restart marks unfinished jobs `interrupted`.
- Tenant isolation is logical (every query and key is tenant-scoped); there is no per-tenant encryption.

# Graphite: AI Safety and EU Regulatory Compliance Auditor

Graphite is an enterprise-grade AI safety and regulatory compliance auditing platform. It audits an organization's code repositories, governance documents, and data pipelines against the **EU AI Act (Regulation 2024/1689)** and the **EU General Data Protection Regulation (GDPR)**, producing evidence-backed, triaged audit reports in JSON, SARIF 2.1.0, and publication-ready 6-section PDFs.

Findings are technical compliance observations for engineering and governance review, not legal advice.

---

## Core Guarantees & Philosophy

1. **Closed-World Assumption (No Evidence != Pass):**
   Missing or inconclusive evidence always yields `SUSPECTED_GAP`, never `PASS`. A control passes only when supported by verifiable AST code facts or document citations.
2. **Quarantine-Over-Drop:**
   Findings that fail validation gates (unresolvable citations, cross-tenant isolation, or weak entailment) are flagged as `QUARANTINED_FOR_HUMAN_REVIEW` with exact diagnostic reasons, never silently discarded.
3. **Cryptographic Proofs & Exact Locators:**
   Every finding includes the SHA-256 hash of the analyzed artifact, file paths, and exact source-code line numbers or document sections.
4. **EU Regulatory Focus:**
   Strictly aligned with the EU statutory perimeter: EU AI Act (Articles 5, 10, 14, 27, 50, 52, 53, 99; Annexes III & IV) and EU GDPR (Articles 5, 9, 22, 28, 44–49).

---

## Architecture Overview

```
                      ┌──────────────────────────────────────────────┐
                      │                 INPUT SOURCES                │
                      │  • Code (Python, TS/JS, Java, Go, C#, etc.)  │
                      │  • Docs (Markdown, Confluence, PDF, Office)  │
                      │  • Data (Schemas, Catalogs, dbt, Parquet)    │
                      └──────────────────────┬───────────────────────┘
                                             │
                                             ▼
                      ┌──────────────────────────────────────────────┐
                      │               EDGE EXTRACTORS                │
                      │  • AST Slices & Model Inference Calls        │
                      │  • Document Assertions & Policy Claims       │
                      │  • Data Asset Classifications                │
                      └──────────────────────┬───────────────────────┘
                                             │
                                             ▼
                      ┌──────────────────────────────────────────────┐
                      │              TRI-MODAL INDEX                 │
                      └──────────────────────┬───────────────────────┘
                                             │
                                             ▼
                      ┌──────────────────────────────────────────────┐
                      │         SUPERVISOR (LangGraph Loop)          │
                      │   Routes tasks to 6 specialized agents:      │
                      │   1. PII Flow & Sovereign Data Residency     │
                      │   2. Human-in-the-Loop (HITL) Oversight      │
                      │   3. Harmful Generation, Safety & Watermarks │
                      │   4. Open-Source & Model License Compliance  │
                      │   5. DPA, Provenance & Technical Files       │
                      │   6. Code-vs-Documentation Policy Drift      │
                      └──────────────────────┬───────────────────────┘
                                             │
                                             ▼
                      ┌──────────────────────────────────────────────┐
                      │             4 GUARDRAIL GATES                │
                      │   Gate 1: Grounded Citation Verification     │
                      │   Gate 2: Multi-Tenant Data Isolation        │
                      │   Gate 3: Code/Doc Entailment & Proof        │
                      │   Gate 4: Severity & Exposure Framing        │
                      └──────────────────────┬───────────────────────┘
                                             │
                                             ▼
                      ┌──────────────────────────────────────────────┐
                      │              DELIVERY OUTPUTS                │
                      │  • Executive PDF (6 Sections, A4 print ready)│
                      │  • SARIF 2.1.0 Export (GitHub Code Scanning) │
                      │  • Automated Remediation Diffs & Fix Patches │
                      │  • Interactive Web Dashboard & Real-Time API │
                      │  • Delta Lake Tables & Atlas History Tracking│
                      └──────────────────────────────────────────────┘
```

---

## Platform Integrations

All components have deterministic offline fallbacks. The system operates fully with or without external credentials.

| Platform | Role in Graphite | Offline Fallback |
|---|---|---|
| **Linkup** | Live regulatory scraping and OSS license verification via deep search | Embedded seed regulatory rules and standard license taxonomies |
| **MongoDB Atlas** | `$vectorSearch` over rules/artifacts, LangGraph state checkpoints (`MongoDBSaver`), longitudinal drift (`audit_history`) | Local BM25 + embedding store, `MemorySaver`, JSON audit history |
| **LangGraph** | Cyclic agent execution graph (`StateGraph`) orchestrating supervisor routing, iterative evaluation loops, and durable state resumption | In-memory cyclic graph with deterministic turn boundaries |
| **Databricks** | Mosaic AI Model Serving, `@mlflow.trace` execution spans, Unity Catalog Delta sinks | Deterministic offline evaluator, no-op telemetry |

---

## Quick Start

### 1. Installation

Requires Python 3.11+, Git, and WeasyPrint system dependencies (Pango/HarfBuzz).

```bash
# Clone the repository
git clone https://github.com/AkhilBaja3005/compliance-agent.git
cd compliance-agent

# Set up virtual environment and install dependencies
make install
# or manually:
python3 -m venv .venv
.venv/bin/pip install -e '.[dev]'

# Configure optional integrations with offline defaults
cp .env.template .env
```

### 2. Verify Environment & Integrations

```bash
# Run integration diagnostics
.venv/bin/graphite doctor
# (Add --live to perform non-destructive read checks against configured cloud endpoints)
```

After installation, activate the environment with `source .venv/bin/activate` to use the commands below.

### 3. Run an Audit Scan

```bash
# Audit a local project directory or repository
graphite scan -t synthetic_companies/merriton_labs_text_verify -c "Merriton Labs" -o merriton_report.pdf

# Export SARIF for GitHub Code Scanning
graphite scan -t synthetic_companies/veylan_analytics_face_identity -c "Veylan Analytics" --sarif-out veylan_report.sarif

# Audit incremental PR changes against a base branch
graphite scan -t synthetic_companies/merriton_labs_text_verify --diff HEAD~1 --fail-on high
```

Scope is set by `GRAPHITE_FRAMEWORKS` (default `EU_AI_ACT,EU_GDPR` or `ALL`). License checks always run. See [reader coverage](docs/coverage.md) for supported inputs. Unchanged files use a content-addressed AST cache (`GRAPHITE_AST_CACHE_DIR=.graphite_cache` persists it between runs); micro-agent checks run in parallel with deterministic ordering (`GRAPHITE_AGENT_WORKERS`, default 6).

Run `graphite demo` to audit all three bundled sample companies and write PDFs plus `demo_output/summary.json`.

### 4. Automated Statutory Remediation

Generate unified diff patches to remediate confirmed violations using an audit report:

```bash
# Generate patch file without modifying code
graphite fix --report report.json --repos <repo_path> --patch-out remediation.patch

# Apply verified patches directly to disk
graphite fix --report report.json --repos <repo_path> --apply
```

### 5. Regulatory Synchronization

Synchronize the regulatory rule library against active EU legislative publications and local policy repositories:

```bash
# Ingest and re-embed statutory sources
graphite sync-laws

# Run continuous sync daemon (or run via cron / systemd)
graphite sync-daemon
```

---

## Interactive Dashboard & Web API

Graphite includes an interactive web dashboard for leadership overviews, engineering finding triage, and continuous audit scheduling.

Open the dashboard and select a company, then choose **Run audit** to create the first assessment. Startup never triggers an audit. Both views refresh every five seconds and preserve the selected company. Failed runs retain the previous completed assessment; empty and disconnected states remain explicit.

The finding explorer supports status, severity, system, jurisdiction and text filters, with expandable evidence, citations, ownership and remediation steps. The UI shows assessment time, refresh time, audit activity, coverage, engine fallback modes, and the latest 30 assessments.

### Local Development Server

```bash
GRAPHITE_AUTH_DISABLED=true BYOM_OFFLINE=true .venv/bin/uvicorn src.api:app --host 127.0.0.1 --port 8000
```

- **Executive Overview:** [http://localhost:8000/dashboard/overview](http://localhost:8000/dashboard/overview)
- **Finding Explorer:** [http://localhost:8000/dashboard/findings](http://localhost:8000/dashboard/findings)
- **Interactive OpenAPI Documentation (Swagger):** [http://localhost:8000/docs](http://localhost:8000/docs)
- **Interactive ReDoc Documentation:** [http://localhost:8000/redoc](http://localhost:8000/redoc)
- **Full API Specification & Endpoints Guide:** [docs/api.md](docs/api.md)

### What Happens When You Click "↻ Run audit" in the Dashboard?

Clicking **"↻ Run audit"** in the top navigation bar triggers a full regulatory and technical audit for the currently selected company/repository.

1. **API Trigger:** The dashboard sends a request to the backend:
   ```http
   POST /dashboard/api/companies/{company_id}/runs
   ```
2. **AST Parsing & Evidence Extraction:**
   - The edge extractors traverse the target codebase, configuration files, and documentation.
   - Extracts AST call chains, model invocation points, prompt templates, training/inference pipelines, and policy assertions.
   - Computes deterministic SHA-256 evidence hashes for every analyzed artifact.
3. **Execution of 7 Specialized Compliance Agents:**
   - **Risk Classification Agent:** Determines risk tiers under the EU AI Act (Prohibited AI Art 5, High-Risk Annex III/Art 6, GPAI Art 51-53, or Minimal Risk).
   - **PII & Data Governance Agent:** Scans data flows and pipeline schemas for personal data, special category data (GDPR Art 9), and third-country data transfers (GDPR Art 44–49).
   - **Human Oversight (HITL) Agent:** Audits fallback routines, override mechanisms, and human intervention logs (EU AI Act Art 14).
   - **Transparency & Watermarking Agent:** Checks synthetic media watermarking, AI disclosures, and user-facing notifications (EU AI Act Art 50).
   - **Robustness & Cybersecurity Agent:** Evaluates model input sanitization, adversarial prompt testing, fail-safe degradation, and technical file completeness (EU AI Act Art 15).
   - **Open Source & Model Licensing Agent:** Cross-references licenses of all dependencies, foundation models, and weights against prohibited or copyleft triggers.
   - **Code-vs-Documentation Drift Agent:** Checks for discrepancies between technical documentation claims and actual AST code implementation.
4. **4 Validation Guardrail Gates:**
   - **Gate 1 (Citation Verification):** Validates citations against verified statutory text.
   - **Gate 2 (Tenant Data Isolation):** Ensures strict separation of cross-tenant proprietary evidence.
   - **Gate 3 (Entailment):** Cryptographically ties findings to AST code evidence or doc locators (enforces Closed-World Assumption).
   - **Gate 4 (Severity & Legal Framing):** Assigns statutory severity (CRITICAL, HIGH, MEDIUM, LOW) and formats findings strictly as technical compliance observations.
5. **Report Generation & Dashboard Refresh:**
   - The resulting `TriagedAuditReport` is persisted in the report store (`ReportStore`).
   - The UI polls every 5 seconds, updating the **Compliance Readiness Score Gauge**, **Priority Action Matrix**, and **Engineering Findings** with real-time evidence locators, remediation guidance, and exportable PDF/SARIF artifacts.

### Comparison: Dashboard "Run audit" vs. CLI (`graphite audit run`)

The Dashboard and CLI share the **identical underlying audit engine** (`src/agents/orchestrator.py:run_audit`), ensuring 100% deterministic parity between developer terminals, CI pipelines, and executive dashboards.

| Dimension | Dashboard ("↻ Run audit") | CLI (`graphite audit run`) |
|---|---|---|
| **Trigger Mechanism** | Browser UI button (`POST /dashboard/api/companies/{id}/runs`) | Terminal command / CI pipeline script |
| **Audit Engine** | `src.agents.orchestrator.run_audit` | `src.agents.orchestrator.run_audit` |
| **Analyzed Assets** | Selected company fixture or configured repository | Workspace, directory, or remote git repository |
| **Agent Execution** | All 7 specialized auditing agents | All 7 specialized auditing agents |
| **Guardrail Gates** | 4 verification & quarantine gates | 4 verification & quarantine gates |
| **Evidence Hashes** | SHA-256 file hashes & exact line locators | SHA-256 file hashes & exact line locators |
| **Output Formats** | Interactive UI, executive charts, downloadable PDF/SARIF/JSON | Terminal stdout, rich summary tables, SARIF 2.1.0, JSON, PDF |
| **Primary Audience** | Compliance officers, risk leaders, engineering managers | Developers, security engineers, CI/CD runners (GitHub Actions) |
| **Execution Mode** | Asynchronous background run with real-time UI polling | Synchronous exit codes (`0` pass, `1` blocking violations) |

### API Endpoints

Authentication is enforced by default via API key headers (`X-API-Key`). Configure access using `GRAPHITE_API_KEYS="key:tenants:role,..."`.

| Route | Role | Purpose |
|---|---|---|
| `GET /healthz`, `/readyz` | Public | Liveness and readiness probes |
| `POST /audit/run` | `auditor` | Synchronous codebase and policy audit |
| `POST /audit/jobs` | `auditor` | Queue asynchronous background audit job (supports `Idempotency-Key`) |
| `GET /audit/jobs/{id}` | `viewer` | Retrieve background job execution status |
| `GET /reports/{id}` | `viewer` | Retrieve stored `TriagedAuditReport` JSON |
| `POST /reports/{id}/signoff` | `auditor` | Cryptographically sign off on audit findings (hash-chained audit ledger) |
| `POST /laws/sync` | `admin` | Trigger immediate regulatory knowledge sync |
| `GET /metrics`, `/stack/status` | `admin` | Prometheus metrics and cloud integration status |

Hardening includes constant-time key checks, per-key rate limits, body-size limits, HTTPS-only allowed repository hosts, confined admin-only local paths, security headers, and JSON logs with request IDs. See the [threat model](docs/threat-model.md) and [operations runbook](docs/runbook.md).

---

## Container Deployment

### Docker Compose

```sh
GRAPHITE_AUTH_DISABLED=true docker compose up --build -d
docker compose logs -f graphite
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
cp .env.template .env
GRAPHITE_AUTH_DISABLED=true podman compose up --build -d
podman compose logs -f graphite
podman compose ps
podman compose down
```

The [Podman environment template](.env.template) lists the variables consumed by
`compose.yaml`, with offline defaults and blank optional credentials. If you already have a
`.env`, merge the settings you need into it instead of replacing it.

The `graphite` service builds the Python 3.11 Debian image, runs as UID/GID 10001, and serves one
Uvicorn process. The default port is bound to localhost. Set `GRAPHITE_PORT=8080` to change the host port.
`GET /healthz` is a lightweight process check, independent of credentials or external services;
the container health check uses it. Use an existing access-control proxy before exposing this
application to other networks. Dashboard data uses the API key roles and tenant scopes. For a protected browser deployment,
configure the proxy to authenticate users and supply a scoped API key on upstream requests.
The commands above explicitly disable authentication for local development.

### Git server in the shared stack

Enable the `git` profile to run the SSH Git server alongside the dashboard in this same
Compose project. First copy your public SSH key to the default authorized-keys location:

```sh
mkdir -p .graphite
cp "$HOME/.ssh/id_ed25519.pub" .graphite/authorized_keys
GRAPHITE_AUTH_DISABLED=true docker compose --profile git up --build -d
# Or: GRAPHITE_AUTH_DISABLED=true podman compose --profile git up --build -d
git clone ssh://git@localhost:2222/demo.git
```

Use `GRAPHITE_AUTHORIZED_KEYS` to select another public authorized-keys file, or
`GRAPHITE_GIT_PORT` to change the SSH host port. The default SSH bind address is localhost;
`GRAPHITE_GIT_BIND_ADDRESS` overrides it. Dedicated public-key and policy bind mounts use
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
  graphite:
    volumes:
      - ./my-repository:/sources/repository:ro
      - ./confluence-export:/sources/confluence:ro
```

For local development, start with `GRAPHITE_AUTH_DISABLED=true docker compose -f compose.yaml -f compose.sources.yaml up --build -d`, or the
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

`.env.template` covers the shared Compose stack with offline defaults and blank optional
credentials. Additional application settings are described below and in the [operations runbook](docs/runbook.md).
The image excludes `.env` files. Container model
URLs must reach the serving host; `localhost` inside a container refers to that container.

### Persistent state and the separate scanner

The named `graphite-state` volume stores async API jobs, reports and sign-off records
(`GRAPHITE_DATA_DIR=/var/lib/graphite`), dashboard reports, company settings and job activity
(`/var/lib/graphite/dashboard.sqlite3`), plus existing finding history
(`/var/lib/graphite/finding-history.json`). `compose down` preserves it; `compose down -v` deletes it.
Back up the stopped volume or use SQLite's backup API for a live database, including WAL data.

Outside containers, `GRAPHITE_DASHBOARD_DB` defaults to `.graphite/dashboard.sqlite3` in the project.
The repository selects MongoDB when the existing compliance store can connect at startup,
otherwise SQLite. A MongoDB fallback is visible in the dashboard. Once a backend is selected,
runtime storage failures surface as errors; the application does not silently switch databases.
Changing backend configuration does not migrate old data.

Every finalized `run_audit` call publishes through one persistence hook, including the existing
synchronous `/audit/run`, CLI calls, and full-audit scanner integrations. Its signature and
return type are unchanged. The scanner should call `run_audit(company_dir, selected_company_id, ...)`
with the same `MONGODB_URI`/database, or the same `GRAPHITE_DASHBOARD_DB` file mounted at a shared path.
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
GRAPHITE_BROWSER_TESTS=1 .venv/bin/pytest -q tests/test_dashboard_browser.py
GRAPHITE_CONTAINER_SMOKE=1 .venv/bin/pytest -q tests/test_dashboard_containers.py
GRAPHITE_CONTAINER_SMOKE=1 .venv/bin/pytest -q tests/test_git_gate_docker.py
docker compose config --quiet
podman compose config --quiet
```

Browser tests start their own local server and exercise both pages, company switching, filtering,
evidence, manual audits, polling, settings, failures, connection recovery and a mobile viewport.
Container tests use isolated Compose projects for each installed runtime, check non-root execution,
health, audit completion and report/settings persistence after restart, then remove their test data.
For a container smoke test, start either stack, check `curl -f http://localhost:8000/healthz`, run
an audit in the dashboard, restart with `compose restart graphite`, and confirm the report persists.
Docker and Podman require their respective installed runtime and Compose provider.
The Git container tests enable the `git` profile in the shared stack and check dashboard
health, SSH clone/push enforcement, and Git persistence for each installed runtime.

---

## Testing & Quality Gate

```bash
# Run unit, integration, and guardrail tests
pytest -q

# Run precision and recall evaluation against gold standard test suite
graphite eval
# or:
pytest tests/test_eval_gate.py
```

`graphite eval` scores confirmed findings against `tests/eval/gold.json` and `tests/test_eval_gate.py` fails CI on a regression. The gold set is small, synthetic and written by the same team that tuned the checks, so a score of 1.0 means the planted defects are found, not that real repositories will be.

---

## Configuration Reference (`.env`)

Copy `.env.template` to `.env` to configure optional remote services:

```ini
# Core scope
GRAPHITE_FRAMEWORKS=EU_AI_ACT,EU_GDPR

# Multi-tenant Auth & API
GRAPHITE_AUTH_DISABLED=false
GRAPHITE_API_KEYS=admin-secret:*:admin,auditor-key:acme|corp:auditor

# Storage & Atlas
MONGODB_URI=mongodb+srv://...
MONGODB_DATABASE=graphite_compliance

# Databricks & MLflow
DATABRICKS_HOST=https://...
DATABRICKS_TOKEN=dapi...
DATABRICKS_SERVING_ENDPOINT=databricks-meta-llama-3-3-70b-instruct
MLFLOW_TRACKING_URI=databricks

# Linkup Deep Search
LINKUP_API_KEY=lk_...
```

---

## Known limitations

- Detection is AST plus regex heuristics (cross-file flows, wrappers and unusual naming are missed). Languages without a grammar (Scala, C/C++, Dart, ...) produce a `COV-01` gap.
- Live Linkup, Atlas, Databricks, MLflow, Notion, Jira, Slack, Drive and SharePoint paths are exercised in tests only against fakes or mocked HTTP.
- Model-based claim extraction has no measured recall. OCR needs `pytesseract` and the tesseract binary.
- Rule text is a paraphrased seed library that counsel has not reviewed. Dates (e.g. Art. 50 transition) are hardcoded.
- A running audit thread cannot be killed: cancel and timeout mark the job and discard the result. A restart marks unfinished jobs `interrupted`.
- Tenant isolation is logical (every query and key is tenant-scoped); there is no per-tenant encryption.

---

## License

This project is licensed under the Apache 2.0 License.

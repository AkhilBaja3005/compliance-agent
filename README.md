# Aegis compliance dashboard

The FastAPI application serves a [leadership overview](http://localhost:8000/dashboard/overview),
an [engineering finding explorer](http://localhost:8000/dashboard/findings), and
[API documentation](http://localhost:8000/docs). Both views use completed `TriagedAuditReport`
results, refresh every five seconds, and preserve the selected company when navigating.
The finding explorer supports status, severity, system, jurisdiction and text filters, with
expandable evidence, citations, ownership and remediation steps.

## Run locally

Requires Python 3.11 or newer, Git, and [WeasyPrint's native libraries](https://doc.courtbouillon.org/weasyprint/latest/first_steps.html#installation).

```sh
python -m venv .venv
.venv/bin/pip install -e '.[dev]'
BYOM_OFFLINE=true .venv/bin/uvicorn src.api:app --host 127.0.0.1 --port 8000 --workers 1
```

Open http://localhost:8000 and select a company. Choose **Run audit** to create the first
assessment. Startup never triggers an audit. The bundled fixtures work without external
credentials. Empty, failed and disconnected states remain explicit; a failed run retains
the previous completed assessment. The UI shows assessment time, successful refresh time,
audit activity, coverage, engine fallback modes, and the latest 30 assessments.

## Docker Compose

```sh
docker compose up --build -d
docker compose logs -f aegis
docker compose ps
docker compose down
```

## Podman Compose

Install Podman and a Compose provider (`podman-compose` or Docker Compose).
[`podman compose` delegates to that provider](https://docs.podman.io/en/latest/markdown/podman-compose.1.html).
The same `compose.yaml` uses standard service, health check, port and volume options.

```sh
podman compose up --build -d
podman compose logs -f aegis
podman compose ps
podman compose down
```

The `aegis` service builds the Python 3.11 Debian image, runs as UID/GID 10001, and serves one
Uvicorn process. The default port is bound to localhost. Set `AEGIS_PORT=8080` to change the host port.
`GET /healthz` is a lightweight process check, independent of credentials or external services;
the container health check uses it. Use an existing access-control proxy before exposing this
application to other networks. The audience views share the existing API's access model.

## Git server in the shared stack

Enable the `git` profile to run the SSH Git server alongside the dashboard in this same
Compose project. First copy your public SSH key to the default authorized-keys location:

```sh
mkdir -p .aegis
cp "$HOME/.ssh/id_ed25519.pub" .aegis/authorized_keys
docker compose --profile git up --build -d
# Or: podman compose --profile git up --build -d
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

## Sources, settings and schedules

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

Start with `docker compose -f compose.yaml -f compose.sources.yaml up --build -d`, or the
equivalent `podman compose` command. On SELinux hosts, use `:ro,Z` for private source mounts,
or `:ro,z` when sharing with another container. Save `/sources/repository` and
`/sources/confluence` in the dashboard. Mounted sources must be readable by UID 10001.
`COMPANIES_DIR` can point to a mounted directory containing `company_*` folders; each folder
is a tenant. Existing company lookup rules still apply.

## Optional services and credentials

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

## Persistent state and the separate scanner

The named `aegis-state` volume stores dashboard reports, company settings and job activity
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

## Dashboard API

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

## Validation

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

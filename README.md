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
```

### 2. Verify Environment & Integrations

```bash
# Run integration diagnostics
graphite doctor
# (Add --live to perform non-destructive read checks against configured cloud endpoints)
```

### 3. Run an Audit Scan

```bash
# Audit a local project directory or repository
graphite scan -t synthetic_companies/merriton_labs_text_verify -c "Merriton Labs" -o merriton_report.pdf

# Export SARIF for GitHub Code Scanning
graphite scan -t synthetic_companies/veylan_analytics_face_identity -c "Veylan Analytics" --sarif veylan_report.sarif

# Audit incremental PR changes against a base branch
graphite scan -t . --diff origin/main --fail-on high
```

### 4. Automated Statutory Remediation

Generate unified diff patches to remediate confirmed violations:

```bash
# Generate patch file without modifying code
graphite fix -t <repo_path> -o remediation.patch

# Apply verified patches directly to disk
graphite fix -t <repo_path> --apply
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

### Local Development Server

```bash
GRAPHITE_AUTH_DISABLED=true BYOM_OFFLINE=true .venv/bin/uvicorn src.api:app --host 127.0.0.1 --port 8000
```

- **Executive Overview:** [http://localhost:8000/dashboard/overview](http://localhost:8000/dashboard/overview)
- **Finding Explorer:** [http://localhost:8000/dashboard/findings](http://localhost:8000/dashboard/findings)
- **Interactive OpenAPI Documentation:** [http://localhost:8000/docs](http://localhost:8000/docs)

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

---

## Container Deployment

### Docker Compose

```bash
# Launch dashboard and scanner stack
GRAPHITE_AUTH_DISABLED=true docker compose up --build -d

# View live logs
docker compose logs -f graphite

# Shutdown
docker compose down
```

### Git Policy Gate Server

Enable server-side pre-receive Git policy enforcement within the shared stack:

```bash
# Set up authorized SSH keys
mkdir -p .graphite
cp "$HOME/.ssh/id_ed25519.pub" .graphite/authorized_keys

# Start with git profile enabled
GRAPHITE_AUTH_DISABLED=true docker compose --profile git up --build -d

# Clone and push through the compliance gate
git clone ssh://git@localhost:2222/demo.git
```

Commits containing unmitigated critical violations (e.g., raw PII egress to non-EU endpoints or solely automated high-risk credit decisions) are rejected at `git push` with actionable remediation guidance.

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

---

## Configuration Reference (`.env`)

Copy `.env.example` to `.env` to configure optional remote services:

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

## License

This project is licensed under the Apache 2.0 License.

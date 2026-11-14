# Graphite REST API Reference

The Graphite compliance auditor exposes a full-featured REST API built with FastAPI.

- **Interactive Swagger UI:** `http://localhost:8000/docs`
- **ReDoc Interactive UI:** `http://localhost:8000/redoc`
- **OpenAPI Schema (JSON):** `http://localhost:8000/openapi.json`

---

## 1. Authentication & Security

All API routes under `/audit/*`, `/reports/*`, and `/admin/*` require an API key passed in the `X-API-Key` HTTP header.

Health checks (`/healthz`, `/readyz`), Prometheus metrics (`/metrics`), and Web Dashboard assets are public.

### API Key Format
Set in the environment as:
```bash
GRAPHITE_API_KEYS="<key>:<tenants>:<role>,..."
# Example:
GRAPHITE_API_KEYS="admin-token:*:admin,auditor-token:merriton|veylan:auditor"
```

To disable authentication for local development:
```bash
export GRAPHITE_AUTH_DISABLED=true
```

### Roles and Permissions
| Role | Allowed Actions |
|---|---|
| `viewer` | Read reports, check job status, view company inventory |
| `auditor` | Trigger audits (sync/async), cancel jobs, sign off on findings |
| `admin` | Sync/simulate laws, ingest PDFs, view system stack status |

---

## 2. Health & Telemetry Endpoints

### `GET /healthz`
Liveness probe.
- **Auth:** None
- **Response:** `200 OK`
```json
{"status": "ok"}
```

### `GET /readyz`
Readiness probe verifying vector stores and database connectivity.
- **Auth:** None
- **Response:** `200 OK` or `503 Service Unavailable`

### `GET /metrics`
Prometheus metrics exposition format.
- **Auth:** None

---

## 3. Audits & Job Execution

### `POST /audit/run`
Executes a synchronous multi-agent compliance scan and returns the triaged report.
- **Role:** `auditor`
- **Request Body:**
```json
{
  "company_id": "merriton_labs_text_verify",
  "github_url": "https://github.com/org/repo",  // Optional
  "confluence_path": "/path/to/docs",          // Optional
  "force_rescan": false
}
```
- **Response:** `200 OK` with full `TriagedAuditReport` schema.

### `POST /audit/jobs`
Queues an asynchronous background audit job. Supports `Idempotency-Key` header.
- **Role:** `auditor`
- **Response:** `202 Accepted`
```json
{
  "job_id": "job-5e600e3b8d16",
  "company_id": "merriton_labs_text_verify",
  "status": "queued",
  "created_at": "2026-11-14T21:55:00Z"
}
```

### `GET /audit/jobs/{job_id}`
Checks the execution status of an asynchronous audit job.
- **Role:** `viewer`
- **Response:** `200 OK` (`queued`, `running`, `completed`, `failed`)

### `GET /audit/jobs/{job_id}/report`
Fetches the completed audit report for a background job.
- **Role:** `viewer`
- **Response:** `200 OK` with `TriagedAuditReport` JSON.

### `POST /audit/jobs/{job_id}/cancel`
Cancels a running or queued job.
- **Role:** `auditor`

---

## 4. Reports & Cryptographic Sign-Off

### `GET /reports/{report_id}`
Retrieves a finalized audit report by its unique ID.
- **Role:** `viewer`

### `POST /reports/{report_id}/signoff`
Attests and cryptographically signs off on an audit report using HMAC/hash chaining.
- **Role:** `auditor`
- **Request Body:**
```json
{
  "signer_name": "Dr. Aris Thorne",
  "signer_role": "Lead Compliance Engineer",
  "attestation": "Reviewed all findings against EU AI Act Article 14 HITL controls.",
  "status": "APPROVED"
}
```
- **Response:** `200 OK`
```json
{
  "report_id": "GRAPHITE-5E600E3B8D16",
  "signature_sha256": "8f4b23...",
  "signed_at": "2026-11-14T22:00:00Z"
}
```

### `GET /reports/{report_id}/signoff`
Retrieves the cryptographic sign-off history and ledger chain for a report.
- **Role:** `viewer`

---

## 5. Regulatory Synchronization & Administration

### `POST /laws/sync`
Triggers immediate synchronization with live EU regulatory sources and Deep Linkup search.
- **Role:** `admin`

### `GET /laws/status`
Returns active statutory index version, rules count, and last synchronization timestamp.
- **Role:** `viewer`

### `GET /stack/status`
Returns connectivity and diagnostics for all 3 cloud engines:
- MongoDB Atlas Vector Search
- Databricks Mosaic AI Model Serving & Unity Catalog
- Linkup Regulatory Search
- **Role:** `admin`

"""FastAPI surface: companies, audits (sync + async jobs), reports and sign-off, law sync, admin, health and metrics.

All routes except /healthz and /readyz require an API key (see src/security.py)."""
from __future__ import annotations

import os
from contextlib import asynccontextmanager
from pathlib import Path

import logging
import time

from fastapi import Depends, FastAPI, Header, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, PlainTextResponse
from pydantic import BaseModel, Field

from src import security as sec
from src.jobs import JobManager, ReportStore
from src.observability import configure_logging, metrics, new_request_id, request_id_var
from src.signoff import SignoffLog

from src.agents import LLMClient, run_audit
from src.edge_extractors import build_index
from src.law_sync import get_store, simulate_law_amendment, sync_now
from src.law_sync.scheduler import law_status, start_scheduler, stop_scheduler
from src.schemas.findings import TriagedAuditReport
from src.schemas.regulatory import Jurisdiction, LawIndexStatus, LawSyncResult

ROOT = Path(__file__).resolve().parent.parent


def companies_root() -> Path:
    """COMPANIES_DIR env > src/synthetic_data > tests/fixtures/companies (first one containing company_* dirs)."""
    candidates = [os.getenv("COMPANIES_DIR"), ROOT / "src" / "synthetic_data", ROOT / "src" / "synthetic_data" / "companies",
                  ROOT / "tests" / "fixtures" / "companies"]
    for c in candidates:
        if c and Path(c).is_dir() and any(p.is_dir() and p.name.startswith("company_") for p in Path(c).iterdir()):
            return Path(c)
    raise RuntimeError("no company directories found")


def list_company_ids() -> list[str]:
    return sorted(p.name for p in companies_root().iterdir() if p.is_dir() and p.name.startswith("company_"))


log = logging.getLogger("aegis.api")


def data_dir() -> Path | None:
    d = os.getenv("AEGIS_DATA_DIR")
    return Path(d) if d else None


class _State:
    jobs: JobManager | None = None
    reports: ReportStore | None = None
    signoffs: SignoffLog | None = None


state = _State()


def _run_job(params: dict) -> dict:
    rep = run_audit(companies_root() / params["company_id"], params["company_id"], LLMClient(), known_tenants=set(list_company_ids()),
                    github_source=params.get("github_url"), confluence_source=params.get("confluence_path") or ("cloud" if params.get("confluence_space_key") else None),
                    space_key=params.get("confluence_space_key"))
    metrics.inc("aegis_audits_total", tenant=params["company_id"])
    for f in rep.all_findings():
        metrics.inc("aegis_findings_total", status=f.status)
    return rep.model_dump(mode="json")


def init_state(force: bool = False) -> None:
    if state.jobs is not None and not force:
        return
    d = data_dir()
    state.reports = ReportStore(d)
    state.jobs = JobManager(_run_job, state.reports, data_dir=d)
    state.signoffs = SignoffLog(d)


@asynccontextmanager
async def lifespan(app: FastAPI):
    configure_logging(os.getenv("AEGIS_LOG_LEVEL", "INFO"))
    init_state()
    if os.getenv("AUTO_SYNC", "false").lower() == "true":
        start_scheduler(24)
    yield
    stop_scheduler()


app = FastAPI(title="Aegis AI Compliance Auditor", lifespan=lifespan)

_origins = [o.strip() for o in os.getenv("AEGIS_CORS_ORIGINS", "").split(",") if o.strip()]
if _origins:  # CORS is off unless origins are listed explicitly
    app.add_middleware(CORSMiddleware, allow_origins=_origins, allow_methods=["GET", "POST"], allow_headers=["Authorization", "Content-Type", "Idempotency-Key", "X-API-Key"])


@app.middleware("http")
async def _edge(request: Request, call_next):
    rid = request.headers.get("x-request-id") or new_request_id()
    request_id_var.set(rid)
    t0 = time.perf_counter()
    max_body = int(os.getenv("AEGIS_MAX_BODY_BYTES", "1048576"))
    cl = request.headers.get("content-length")
    if cl and cl.isdigit() and int(cl) > max_body:
        resp = JSONResponse({"detail": "request body too large"}, status_code=413)
    else:
        try:
            resp = await call_next(request)
        except Exception:
            log.exception("unhandled error", extra={"method": request.method, "path": request.url.path})
            resp = JSONResponse({"detail": "internal error", "request_id": rid}, status_code=500)
    for k, v in sec.SECURITY_HEADERS.items():
        resp.headers.setdefault(k, v)
    resp.headers["X-Request-ID"] = rid
    ms = round((time.perf_counter() - t0) * 1000, 1)
    p = getattr(request.state, "principal", None)
    metrics.inc("aegis_http_requests_total", method=request.method, status=resp.status_code)
    log.info("request", extra={"method": request.method, "path": request.url.path, "status": resp.status_code, "duration_ms": ms, "key_id": getattr(p, "key_id", "-")})
    return resp


class CompanyInfo(BaseModel):
    company_id: str
    company_name: str
    sector: str
    python_files: int
    documents: int


class AuditRequest(BaseModel):
    company_id: str = Field(min_length=1, max_length=120)
    inject_fake_citation: bool = False  # demo: tamper one evidence hash to exercise Gate 1
    github_url: str | None = Field(None, max_length=500)  # https URL on an allow-listed host (shallow-cloned, deleted after scan) or admin-only local path
    confluence_space_key: str | None = Field(None, max_length=60)  # live Atlassian Cloud space (CONFLUENCE_* env)
    confluence_path: str | None = Field(None, max_length=500)  # admin-only local Confluence export folder


class SimulateRequest(BaseModel):
    jurisdiction: Jurisdiction = "EU_AI_ACT"
    title: str | None = Field(None, max_length=300)
    text: str | None = Field(None, max_length=20000)


class SignoffRequest(BaseModel):
    decision: str
    reviewer_name: str = Field(min_length=1, max_length=120)
    note: str = Field("", max_length=2000)
    finding_id: str | None = Field(None, max_length=200)


# ------------------------------------------------------------------ health
@app.get("/healthz")
def healthz():
    return {"status": "ok"}


@app.get("/readyz")
def readyz():
    checks = {}
    try:
        checks["companies"] = len(list_company_ids())
    except Exception as exc:
        checks["companies"] = f"error: {type(exc).__name__}"
    try:
        checks["rules"] = len(get_store().snapshot())
    except Exception as exc:
        checks["rules"] = f"error: {type(exc).__name__}"
    checks["auth"] = "disabled (dev)" if sec.auth_disabled() else ("configured" if sec._load_keys() else "NOT CONFIGURED")
    ok = all(not str(v).startswith(("error", "NOT")) for v in checks.values())
    return JSONResponse({"status": "ready" if ok else "not_ready", "checks": checks}, status_code=200 if ok else 503)


@app.get("/metrics", response_class=PlainTextResponse)
def metrics_endpoint(_: sec.Principal = Depends(sec.require("admin"))):
    return metrics.render()


# ------------------------------------------------------------------ companies and audits
@app.get("/companies", response_model=list[CompanyInfo])
def companies(p: sec.Principal = Depends(sec.require("viewer")), _rl: None = Depends(sec.rate_limit())):
    root, out = companies_root(), []
    for cid in list_company_ids():
        if not p.can_access(cid):
            continue
        ix = build_index(root / cid, cid)
        out.append(CompanyInfo(company_id=cid, company_name=ix.company_name, sector=ix.sector,
                               python_files=len(ix.py_files), documents=len({c.doc_name for c in ix.chunks})))
    return out


def _fake_citation(findings) -> None:
    for f in findings:
        if f.evidence:
            f.evidence[0] = f.evidence[0].model_copy(update={"sha256_hash": "0" * 64})
            return


def _validated(req: AuditRequest, p: sec.Principal) -> dict:
    if req.company_id not in list_company_ids():
        raise HTTPException(404, f"unknown company '{req.company_id}'")
    sec.require_tenant(p, req.company_id)
    root = companies_root()
    params = req.model_dump()
    if req.github_url:
        params["github_url"] = sec.validate_repo_source(req.github_url, p, root)
    if req.confluence_path:
        params["confluence_path"] = str(sec.validate_local_path(req.confluence_path, [root], p))
    return params


@app.post("/audit/run", response_model=TriagedAuditReport)
def audit_run(req: AuditRequest, p: sec.Principal = Depends(sec.require("auditor")), _rl: None = Depends(sec.rate_limit(heavy=True))):
    params = _validated(req, p)
    metrics.inc("aegis_audits_total", tenant=req.company_id)
    return run_audit(companies_root() / req.company_id, req.company_id, LLMClient(),
                     tamper=_fake_citation if req.inject_fake_citation else None, known_tenants=set(list_company_ids()),
                     github_source=params.get("github_url"), confluence_source=params.get("confluence_path") or ("cloud" if req.confluence_space_key else None),
                     space_key=req.confluence_space_key)


@app.post("/audit/jobs", status_code=202)
def audit_job_submit(req: AuditRequest, idempotency_key: str | None = Header(None, alias="Idempotency-Key", max_length=120),
                     p: sec.Principal = Depends(sec.require("auditor")), _rl: None = Depends(sec.rate_limit(heavy=True))):
    params = _validated(req, p)
    params.pop("inject_fake_citation", None)  # the tamper demo is only available on the synchronous endpoint
    init_state()
    job, created = state.jobs.submit(req.company_id, params, p.key_id, idempotency_key)
    log.info("job submitted", extra={"job_id": job.job_id, "tenant": req.company_id, "event": "created" if created else "idempotent_replay"})
    return JSONResponse(job.public(), status_code=202 if created else 200, headers={"Location": f"/audit/jobs/{job.job_id}"})


def _job_for(job_id: str, p: sec.Principal):
    init_state()
    j = state.jobs.get(job_id)
    if j is None or not p.can_access(j.tenant):  # same answer for unknown and forbidden: no tenant enumeration
        raise HTTPException(404, "job not found")
    return j


@app.get("/audit/jobs/{job_id}")
def audit_job_status(job_id: str, p: sec.Principal = Depends(sec.require("viewer")), _rl: None = Depends(sec.rate_limit())):
    return _job_for(job_id, p).public()


@app.post("/audit/jobs/{job_id}/cancel")
def audit_job_cancel(job_id: str, p: sec.Principal = Depends(sec.require("auditor"))):
    _job_for(job_id, p)
    return state.jobs.cancel(job_id).public()


@app.get("/audit/jobs/{job_id}/report", response_model=TriagedAuditReport)
def audit_job_report(job_id: str, p: sec.Principal = Depends(sec.require("viewer"))):
    j = _job_for(job_id, p)
    if j.status != "succeeded" or not j.report_id:
        raise HTTPException(409, f"job is {j.status}")
    return state.reports.get(j.report_id)[1]


# ------------------------------------------------------------------ reports and sign-off
def _report_for(report_id: str, p: sec.Principal):
    init_state()
    found = state.reports.get(report_id)
    if found is None or not p.can_access(found[0]):
        raise HTTPException(404, "report not found")
    return found


@app.get("/reports/{report_id}", response_model=TriagedAuditReport)
def report_get(report_id: str, p: sec.Principal = Depends(sec.require("viewer"))):
    return _report_for(report_id, p)[1]


@app.post("/reports/{report_id}/signoff", status_code=201)
def report_signoff(report_id: str, req: SignoffRequest, p: sec.Principal = Depends(sec.require("auditor"))):
    tenant, rep = _report_for(report_id, p)
    ids = {f["finding_id"] for k in ("confirmed_findings", "suspected_gaps", "quarantined_for_human_review", "passed_checks") for f in rep.get(k, [])}
    if req.finding_id and req.finding_id not in ids:
        raise HTTPException(404, "finding not in this report")
    try:
        rec = state.signoffs.add(report_id, tenant, req.finding_id, req.decision, p.key_id, req.reviewer_name, req.note)
    except ValueError as exc:
        raise HTTPException(422, str(exc))
    log.info("signoff", extra={"event": req.decision, "tenant": tenant, "key_id": p.key_id})
    return rec


@app.get("/reports/{report_id}/signoff")
def report_signoff_status(report_id: str, p: sec.Principal = Depends(sec.require("viewer"))):
    _, rep = _report_for(report_id, p)
    ids = [f["finding_id"] for k in ("confirmed_findings", "suspected_gaps", "quarantined_for_human_review") for f in rep.get(k, [])]
    ok, bad = state.signoffs.verify()
    return {"status": state.signoffs.status(report_id, ids), "records": state.signoffs.for_report(report_id), "chain_valid": ok, "first_bad_seq": bad,
            "note": "Findings are recommendations until a named human signs them off."}


# ------------------------------------------------------------------ laws, stack, admin
@app.post("/laws/sync", response_model=LawSyncResult)
def laws_sync(_: sec.Principal = Depends(sec.require("admin"))):
    return sync_now()


@app.post("/laws/simulate-update", response_model=LawSyncResult)
def laws_simulate(req: SimulateRequest | None = None, _: sec.Principal = Depends(sec.require("admin"))):
    req = req or SimulateRequest()
    return simulate_law_amendment(req.jurisdiction, req.title, req.text)


@app.get("/laws/pending")
def laws_pending(_: sec.Principal = Depends(sec.require("admin"))):
    """Rule updates staged for human review (only when AEGIS_RULE_REVIEW_REQUIRED=true)."""
    st = get_store()
    return [{"pending_id": k, "source": v["source"], "created_at": v["created_at"], "changes": [c.model_dump() for c in v["changes"]]} for k, v in st.pending.items()]


@app.post("/laws/pending/{pending_id}/approve", response_model=LawSyncResult)
def laws_approve(pending_id: str, reviewer_name: str = Query(min_length=1, max_length=120), p: sec.Principal = Depends(sec.require("admin"))):
    try:
        return get_store().approve_pending(pending_id, f"{reviewer_name} [{p.key_id}]")
    except KeyError:
        raise HTTPException(404, "no such pending update")


@app.post("/laws/pending/{pending_id}/reject")
def laws_reject(pending_id: str, _: sec.Principal = Depends(sec.require("admin"))):
    if not get_store().reject_pending(pending_id):
        raise HTTPException(404, "no such pending update")
    return {"rejected": pending_id}


@app.get("/laws/status", response_model=LawIndexStatus)
def laws_status(_: sec.Principal = Depends(sec.require("viewer"))):
    return law_status()


@app.get("/stack/status")
def stack_status(_: sec.Principal = Depends(sec.require("admin"))):
    """Which platform engines are live vs. running their offline fallback."""
    from src.law_sync.linkup_scout import get_scout
    from src.storage import DatabricksGovernanceSink, get_compliance_store

    llm, sink, mongo = LLMClient(), DatabricksGovernanceSink(), get_compliance_store()
    return {"linkup": "live" if get_scout().enabled else "disabled (LINKUP_API_KEY unset)",
            "mongodb": mongo.describe(),
            "databricks_model_serving": llm.databricks_endpoint or "offline-fallback",
            "unity_catalog": "enabled" if sink.enabled else "disabled (DATABRICKS_WAREHOUSE_ID unset)",
            "mlflow_tracing": "enabled" if __import__("src.agents.tracing", fromlist=["x"]).tracing_enabled() else "no-op"}


class PDFIngestRequest(BaseModel):
    pdf_path: str = Field(max_length=500)
    jurisdiction: str = Field("EU_AI_ACT", max_length=40)
    tenant_id: str = Field("global_regulations", max_length=120)
    doc_category: str = Field("REGULATORY_PDF", max_length=40)


def pdf_roots() -> list[Path]:
    return [Path(os.getenv("AEGIS_PDF_ROOT", ROOT / "regulatory_pdfs"))]


@app.post("/admin/ingest-pdf")
def admin_ingest_pdf(req: PDFIngestRequest, p: sec.Principal = Depends(sec.require("admin"))):
    """Admin endpoint to ingest and index a regulatory or policy PDF into MongoDB Atlas + local retriever."""
    from src.edge_extractors.pdf_ingestor import ingest_pdf_file
    from src.storage import get_compliance_store

    path = sec.validate_local_path(req.pdf_path, pdf_roots(), p)  # only files under AEGIS_PDF_ROOT
    if not path.is_file() or path.suffix.lower() != ".pdf":
        raise HTTPException(status_code=404, detail="PDF file not found")
    chunks = ingest_pdf_file(pdf_path=path, jurisdiction=req.jurisdiction, tenant_id=req.tenant_id, doc_category=req.doc_category)
    store = get_compliance_store()
    count = store.index_pdf_chunks(chunks)
    return {"status": "SUCCESS", "filename": path.name, "jurisdiction": req.jurisdiction, "tenant_id": req.tenant_id,
            "chunks_indexed": count, "is_atlas": store.is_atlas}


@app.get("/admin/search-rules")
def admin_search_rules(q: str = Query(max_length=500), jurisdiction: str | None = None, top_k: int = 5, _: sec.Principal = Depends(sec.require("admin"))):
    """Admin endpoint to query indexed statutory rules and PDF passages."""
    from src.storage import get_compliance_store

    store = get_compliance_store()
    results = store.search_regulatory_knowledge(query=q, jurisdiction=jurisdiction, top_k=max(1, min(top_k, 20)))
    return {"query": q, "jurisdiction": jurisdiction, "count": len(results), "results": results}

"""FastAPI surface: /companies, /audit/run, /laws/sync, /laws/simulate-update, /laws/status."""
from __future__ import annotations

import asyncio
import logging
import os
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from src.agents import LLMClient, run_audit
from src.dashboard.routes import STATIC, router as dashboard_router
from src.edge_extractors import build_index
from src.law_sync import simulate_law_amendment, sync_now
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


@asynccontextmanager
async def lifespan(app: FastAPI):
    from src.dashboard.service import DashboardService
    from src.storage.dashboard import get_dashboard_repository

    app.state.dashboard = None
    try:
        dashboard = DashboardService(get_dashboard_repository(), list_company_ids, companies_root)
        dashboard.start()
        app.state.dashboard = dashboard
    except Exception as exc:
        logging.getLogger(__name__).error("Dashboard startup failed: %s", type(exc).__name__)
    if os.getenv("AUTO_SYNC", "false").lower() == "true":
        start_scheduler(24)
    try:
        yield
    finally:
        stop_scheduler()
        if app.state.dashboard is not None:
            await asyncio.to_thread(app.state.dashboard.stop)
            app.state.dashboard = None


app = FastAPI(title="EU & UK AI Compliance Auditor", lifespan=lifespan)

app.include_router(dashboard_router)
app.mount("/dashboard/static", StaticFiles(directory=STATIC), name="dashboard-static")


@app.middleware("http")
async def dashboard_storage_errors(request: Request, call_next):
    if request.url.path.startswith("/dashboard/api/"):
        try:
            return await call_next(request)
        except Exception as exc:
            logging.getLogger(__name__).error("Dashboard request failed: %s", type(exc).__name__)
            return JSONResponse(status_code=503, content={"detail": "Dashboard storage unavailable; check server logs"})
    return await call_next(request)


@app.get("/healthz")
def healthz():
    """Process health only: no external services, filesystem scans or model calls."""
    return {"status": "ok"}


class CompanyInfo(BaseModel):
    company_id: str
    company_name: str
    sector: str
    python_files: int
    documents: int


class AuditRequest(BaseModel):
    company_id: str
    inject_fake_citation: bool = False  # demo: tamper one evidence hash to exercise Gate 1
    github_url: str | None = None  # live repo (shallow-cloned with GITHUB_TOKEN, deleted after scan) or local path
    confluence_space_key: str | None = None  # live Atlassian Cloud space (CONFLUENCE_* env)
    confluence_path: str | None = None  # local Confluence export folder


class SimulateRequest(BaseModel):
    jurisdiction: Jurisdiction = "EU_AI_ACT"
    title: str | None = None
    text: str | None = None


@app.get("/companies", response_model=list[CompanyInfo])
def companies():
    root, out = companies_root(), []
    for cid in list_company_ids():
        ix = build_index(root / cid, cid)
        out.append(CompanyInfo(company_id=cid, company_name=ix.company_name, sector=ix.sector,
                               python_files=len(ix.py_files), documents=len({c.doc_name for c in ix.chunks})))
    return out


def _fake_citation(findings) -> None:
    for f in findings:
        if f.evidence:
            f.evidence[0] = f.evidence[0].model_copy(update={"sha256_hash": "0" * 64})
            return


@app.post("/audit/run", response_model=TriagedAuditReport)
def audit_run(req: AuditRequest):
    if req.company_id not in list_company_ids():
        raise HTTPException(404, f"unknown company '{req.company_id}'")
    return run_audit(companies_root() / req.company_id, req.company_id, LLMClient(),
                     tamper=_fake_citation if req.inject_fake_citation else None, known_tenants=set(list_company_ids()),
                     github_source=req.github_url, confluence_source=req.confluence_path or ("cloud" if req.confluence_space_key else None),
                     space_key=req.confluence_space_key)


@app.post("/laws/sync", response_model=LawSyncResult)
def laws_sync():
    return sync_now()


@app.post("/laws/simulate-update", response_model=LawSyncResult)
def laws_simulate(req: SimulateRequest | None = None):
    req = req or SimulateRequest()
    return simulate_law_amendment(req.jurisdiction, req.title, req.text)


@app.get("/laws/status", response_model=LawIndexStatus)
def laws_status():
    return law_status()


@app.get("/stack/status")
def stack_status():
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
    pdf_path: str
    jurisdiction: str = "EU_AI_ACT"
    tenant_id: str = "global_regulations"
    doc_category: str = "REGULATORY_PDF"


@app.post("/admin/ingest-pdf")
def admin_ingest_pdf(req: PDFIngestRequest):
    """Admin endpoint to ingest and index a regulatory or policy PDF into MongoDB Atlas + local retriever."""
    from src.edge_extractors.pdf_ingestor import ingest_pdf_file
    from src.storage import get_compliance_store

    p = Path(req.pdf_path).resolve()
    if not p.is_file():
        raise HTTPException(status_code=404, detail=f"PDF file not found at: {req.pdf_path}")

    chunks = ingest_pdf_file(
        pdf_path=p,
        jurisdiction=req.jurisdiction,
        tenant_id=req.tenant_id,
        doc_category=req.doc_category,
    )
    store = get_compliance_store()
    count = store.index_pdf_chunks(chunks)
    return {
        "status": "SUCCESS",
        "filename": p.name,
        "jurisdiction": req.jurisdiction,
        "tenant_id": req.tenant_id,
        "chunks_indexed": count,
        "is_atlas": store.is_atlas,
    }


@app.get("/admin/search-rules")
def admin_search_rules(q: str, jurisdiction: str | None = None, top_k: int = 5):
    """Admin endpoint to query indexed statutory rules and PDF passages."""
    from src.storage import get_compliance_store

    store = get_compliance_store()
    results = store.search_regulatory_knowledge(query=q, jurisdiction=jurisdiction, top_k=top_k)
    return {
        "query": q,
        "jurisdiction": jurisdiction,
        "count": len(results),
        "results": results,
    }

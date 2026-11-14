"""FastAPI surface: /companies, /audit/run, /laws/sync, /laws/simulate-update, /laws/status."""
from __future__ import annotations

import os
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

from src.agents import LLMClient, run_audit
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
    if os.getenv("AUTO_SYNC", "false").lower() == "true":
        start_scheduler(24)
    yield
    stop_scheduler()


app = FastAPI(title="EU & UK AI Compliance Auditor", lifespan=lifespan)


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

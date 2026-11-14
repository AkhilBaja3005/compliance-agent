"""Dashboard pages and tenant-scoped API."""
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from fastapi.responses import FileResponse, RedirectResponse

from src import security as sec
from src.dashboard.models import Job, Settings, Snapshot, Sources
from src.dashboard.service import DashboardService
from src.schemas.findings import TriagedAuditReport

router = APIRouter()
STATIC = Path(__file__).parent / "static"


def service(request: Request, company_id: str, p: sec.Principal = Depends(sec.require("viewer")),
            _rl: None = Depends(sec.rate_limit())) -> DashboardService:
    from src.api import list_company_ids

    sec.require_tenant(p, company_id)
    if company_id not in list_company_ids():
        raise HTTPException(404, "Unknown company")
    instance = getattr(request.app.state, "dashboard", None)
    if instance is None:
        raise HTTPException(503, "Dashboard storage unavailable; check server logs")
    return instance


def validate_sources(sources: Sources, p: sec.Principal) -> None:
    if sec.auth_disabled():
        return  # local development supports explicitly mounted source directories
    from src.api import companies_root

    root = companies_root()
    if sources.github_url:
        sec.validate_repo_source(sources.github_url, p, root)
    if sources.confluence_path:
        sec.validate_local_path(sources.confluence_path, [root], p)


@router.get("/", include_in_schema=False)
def home():
    return RedirectResponse("/dashboard/overview")


@router.get("/dashboard", include_in_schema=False)
def dashboard_home():
    return RedirectResponse("/dashboard/overview")


@router.get("/dashboard/overview", include_in_schema=False)
@router.get("/dashboard/findings", include_in_schema=False)
def page():
    return FileResponse(STATIC / "index.html", headers={"Cache-Control": "no-cache"})


@router.get("/dashboard/api/companies/{company_id}/snapshot", response_model=Snapshot)
def snapshot(company_id: str, response: Response, dashboard: DashboardService = Depends(service)):
    response.headers["Cache-Control"] = "no-store"
    return dashboard.snapshot(company_id)


@router.get("/dashboard/api/companies/{company_id}/reports/{report_id}", response_model=TriagedAuditReport)
def report(company_id: str, report_id: str, response: Response, dashboard: DashboardService = Depends(service)):
    result = dashboard.repository.get_report(company_id, report_id)
    if result is None:
        raise HTTPException(404, "Report not found for this company")
    response.headers["Cache-Control"] = "no-store"
    return result


@router.post("/dashboard/api/companies/{company_id}/runs", response_model=Job, status_code=202)
def run(company_id: str, dashboard: DashboardService = Depends(service), p: sec.Principal = Depends(sec.require("auditor")),
        _rl: None = Depends(sec.rate_limit(heavy=True))):
    validate_sources(dashboard.repository.get_settings(company_id).sources, p)
    return dashboard.enqueue(company_id)


@router.get("/dashboard/api/companies/{company_id}/runs/{job_id}", response_model=Job)
def job(company_id: str, job_id: str, response: Response, dashboard: DashboardService = Depends(service)):
    result = dashboard.repository.get_job(company_id, job_id)
    if result is None:
        raise HTTPException(404, "Job not found for this company")
    response.headers["Cache-Control"] = "no-store"
    return result


@router.put("/dashboard/api/companies/{company_id}/settings", response_model=Settings)
def settings(company_id: str, value: Settings, dashboard: DashboardService = Depends(service), p: sec.Principal = Depends(sec.require("auditor"))):
    validate_sources(value.sources, p)
    return dashboard.save_settings(company_id, value)

"""Dashboard pages and tenant-scoped API."""
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from fastapi.responses import FileResponse, RedirectResponse

from src.dashboard.models import Job, Settings, Snapshot
from src.dashboard.service import DashboardService
from src.schemas.findings import TriagedAuditReport

router = APIRouter()
STATIC = Path(__file__).parent / "static"


def service(request: Request, company_id: str) -> DashboardService:
    from src.api import list_company_ids

    if company_id not in list_company_ids():
        raise HTTPException(404, "Unknown company")
    instance = getattr(request.app.state, "dashboard", None)
    if instance is None:
        raise HTTPException(503, "Dashboard storage unavailable; check server logs")
    return instance


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
def run(company_id: str, dashboard: DashboardService = Depends(service)):
    return dashboard.enqueue(company_id)


@router.get("/dashboard/api/companies/{company_id}/runs/{job_id}", response_model=Job)
def job(company_id: str, job_id: str, response: Response, dashboard: DashboardService = Depends(service)):
    result = dashboard.repository.get_job(company_id, job_id)
    if result is None:
        raise HTTPException(404, "Job not found for this company")
    response.headers["Cache-Control"] = "no-store"
    return result


@router.put("/dashboard/api/companies/{company_id}/settings", response_model=Settings)
def settings(company_id: str, value: Settings, dashboard: DashboardService = Depends(service)):
    return dashboard.save_settings(company_id, value)

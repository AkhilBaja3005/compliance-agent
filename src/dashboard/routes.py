"""Dashboard pages and tenant-scoped API."""
import logging
from pathlib import Path

log = logging.getLogger("graphite.dashboard")

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse

from src import security as sec
from src.dashboard.models import Job, Settings, Snapshot, Sources
from src.dashboard.service import DashboardService
from src.schemas.findings import TriagedAuditReport

router = APIRouter()
STATIC = Path(__file__).parent / "static"
ASSETS = Path(__file__).resolve().parents[2] / "assets"


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
    landing_file = STATIC / "landing.html"
    if landing_file.is_file():
        return FileResponse(landing_file, headers={"Cache-Control": "no-cache"})
    return RedirectResponse("/dashboard/overview")


@router.post("/", include_in_schema=False)
async def submit_demo(request: Request):
    """Handles demo requests from landing page and dispatches email via Resend."""
    import os
    import json
    import urllib.request
    from datetime import datetime, timezone

    email = ""
    try:
        form_data = await request.form()
        email = form_data.get("email", "").strip()
    except Exception:
        pass

    if email:
        log.info("Demo requested: %s", email)
        owner_emails_raw = os.getenv(
            "OWNER_EMAILS",
            "akhilbaja.work@gmail.com,aryantiwariofficial1@gmail.com",
        )
        owner_list = [addr.strip() for addr in owner_emails_raw.split(",") if addr.strip()]
        
        email_sent = False

        # 1. Attempt delivery via direct Gmail SMTP (Highest inbox deliverability, no spam flagging)
        smtp_host = os.getenv("SMTP_HOST", "smtp.gmail.com")
        smtp_port = int(os.getenv("SMTP_PORT", "587"))
        smtp_user = os.getenv("SMTP_USER", "")
        smtp_password = os.getenv("SMTP_PASSWORD", "")
        email_from = os.getenv("EMAIL_FROM", smtp_user)

        if smtp_user and smtp_password:
            try:
                import smtplib
                from email.mime.text import MIMEText
                from email.mime.multipart import MIMEMultipart

                msg = MIMEMultipart("alternative")
                msg["Subject"] = f"Graphite AI — New Demo Request from {email}"
                msg["From"] = f"Graphite AI <{email_from}>"
                msg["To"] = ", ".join(owner_list)

                html_content = (
                    f"<div style='font-family:sans-serif;line-height:1.6;color:#111;max-width:600px;margin:auto;padding:20px;border:1px solid #e0e0e0;border-radius:8px;'>"
                    f"<h2 style='color:#006DDD;'>Graphite AI — Demo Request</h2>"
                    f"<p>A new demo request has been submitted on the Graphite AI platform.</p>"
                    f"<p><strong>Prospect Email:</strong> <a href='mailto:{email}'>{email}</a></p>"
                    f"<p><strong>Timestamp:</strong> {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')}</p>"
                    f"<hr style='border:0;border-top:1px solid #eee;margin:20px 0;'/>"
                    f"<p style='font-size:12px;color:#777;'>Sent directly via Gmail SMTP Mailer</p>"
                    f"</div>"
                )
                msg.attach(MIMEText(html_content, "html"))

                with smtplib.SMTP(smtp_host, smtp_port, timeout=10) as server:
                    server.starttls()
                    server.login(smtp_user, smtp_password)
                    server.sendmail(email_from, owner_list, msg.as_string())
                
                log.info("Gmail SMTP email dispatched successfully to %s", owner_list)
                email_sent = True
            except Exception as exc:
                log.warning("Gmail SMTP dispatch failed: %s", exc)

        # 2. Fallback to Brevo transactional API if configured
        brevo_key = os.getenv("BREVO_API_KEY", "")
        if not email_sent and brevo_key:
            try:
                import socket
                orig_getaddrinfo = socket.getaddrinfo
                try:
                    def _ipv4_addrinfo(host, port, family=0, type=0, proto=0, flags=0):
                        return orig_getaddrinfo(host, port, socket.AF_INET, type, proto, flags)
                    socket.getaddrinfo = _ipv4_addrinfo

                    brevo_sender = os.getenv("BREVO_SENDER_EMAIL", os.getenv("SMTP_USER", "akhilkumarbaja@gmail.com"))
                    brevo_body = {
                        "sender": {"name": "Graphite AI", "email": brevo_sender},
                        "to": [{"email": o} for o in owner_list],
                        "subject": f"Graphite AI — New Demo Request from {email}",
                        "htmlContent": (
                            f"<div style='font-family:sans-serif;line-height:1.6;color:#111;max-width:600px;margin:auto;padding:20px;border:1px solid #e0e0e0;border-radius:8px;'>"
                            f"<h2 style='color:#006DDD;'>Graphite AI — Demo Request</h2>"
                            f"<p>A new demo request has been submitted on the Graphite AI platform.</p>"
                            f"<p><strong>Prospect Email:</strong> <a href='mailto:{email}'>{email}</a></p>"
                            f"<p><strong>Timestamp:</strong> {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')}</p>"
                            f"<hr style='border:0;border-top:1px solid #eee;margin:20px 0;'/>"
                            f"<p style='font-size:12px;color:#777;'>Powered by Graphite AI Regulatory Compliance Auditor & Brevo</p>"
                            f"</div>"
                        ),
                    }
                    req = urllib.request.Request(
                        "https://api.brevo.com/v3/smtp/email",
                        headers={
                            "api-key": brevo_key,
                            "Content-Type": "application/json",
                            "Accept": "application/json",
                            "User-Agent": "Graphite-Compliance/1.0",
                        },
                        data=json.dumps(brevo_body).encode("utf-8"),
                        method="POST",
                    )
                    with urllib.request.urlopen(req, timeout=5) as resp:
                        log.info("Brevo email dispatched successfully to %s (Status: %s)", owner_list, resp.status)
                        email_sent = True
                finally:
                    socket.getaddrinfo = orig_getaddrinfo
            except Exception as exc:
                log.warning("Brevo email dispatch failed: %s", exc)

        # 3. Fallback to Resend if needed
        resend_key = os.getenv("RESEND_API_KEY", "")
        if not email_sent and resend_key:
            for target_recipients in [owner_list, ["akhilkumarbaja@gmail.com"]]:
                try:
                    resend_body = {
                        "from": "onboarding@resend.dev",
                        "to": target_recipients,
                        "subject": f"Graphite AI — New Demo Request from {email}",
                        "html": (
                            f"<div style='font-family:sans-serif;line-height:1.6;color:#111;max-width:600px;margin:auto;padding:20px;border:1px solid #e0e0e0;border-radius:8px;'>"
                            f"<h2 style='color:#006DDD;'>Graphite AI — Demo Request</h2>"
                            f"<p>A new demo request has been submitted on the Graphite AI platform.</p>"
                            f"<p><strong>Prospect Email:</strong> <a href='mailto:{email}'>{email}</a></p>"
                            f"<p><strong>Timestamp:</strong> {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')}</p>"
                            f"<hr style='border:0;border-top:1px solid #eee;margin:20px 0;'/>"
                            f"<p style='font-size:12px;color:#777;'>Powered by Graphite AI Regulatory Compliance Auditor</p>"
                            f"</div>"
                        ),
                    }
                    req = urllib.request.Request(
                        "https://api.resend.com/emails",
                        headers={
                            "Authorization": f"Bearer {resend_key}",
                            "Content-Type": "application/json",
                            "User-Agent": "Graphite-Compliance/1.0",
                        },
                        data=json.dumps(resend_body).encode("utf-8"),
                        method="POST",
                    )
                    with urllib.request.urlopen(req, timeout=5) as resp:
                        log.info("Resend fallback email dispatched to %s (Status: %s)", target_recipients, resp.status)
                        break
                except Exception as exc:
                    log.warning("Resend dispatch attempt failed: %s", exc)




    return JSONResponse({"status": "ok", "message": "Demo request received"})





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

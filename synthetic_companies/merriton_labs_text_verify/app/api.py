from pathlib import Path
from fastapi import FastAPI, Request, Depends, Header, Query
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse, Response, PlainTextResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from .domain import Principal
from .errors import ProductError, safe_error
from .exports import export_advice
from .http_limits import BodyLimit
from .schemas import SubmissionRequest, BatchRequest, ReviewRequest, SessionRequest
from .service import VerifyService
from .worker import run_one

ROOT = Path(__file__).resolve().parent


def create_app(service: VerifyService, local_sessions: bool = False) -> FastAPI:
    app = FastAPI(title="DemoText Verify", docs_url=None, redoc_url=None, openapi_url=None)
    app.state.service = service
    app.add_middleware(BodyLimit)
    app.mount("/static", StaticFiles(directory=ROOT / "static"), name="static")
    templates = Jinja2Templates(directory=ROOT / "templates")

    @app.middleware("http")
    async def safe_http(request: Request, call_next):
        if request.method not in {"GET", "HEAD", "OPTIONS"} and request.headers.get("x-demotext-client") != "editor-v1":
            response = JSONResponse({**safe_error(ProductError("forbidden", 403)),
                                     "notice": service.notices.current()}, status_code=403)
        else:
            try:
                response = await call_next(request)
            except Exception:
                response = JSONResponse({**safe_error(ProductError("internal_error", 500)),
                                         "notice": service.notices.current()}, status_code=500)
        response.headers["Cache-Control"] = "no-store"
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["Content-Security-Policy"] = "default-src 'self'; script-src 'self'; style-src 'self'; object-src 'none'; base-uri 'none'; frame-ancestors 'none'; form-action 'self'"
        return response

    @app.exception_handler(ProductError)
    async def product_error(request: Request, error: ProductError):
        return JSONResponse({**safe_error(error), "notice": service.notices.current()}, status_code=error.status)

    @app.exception_handler(RequestValidationError)
    async def invalid_request(request: Request, error: RequestValidationError):
        # FastAPI's default detail can echo submitted content; never serialize it.
        return JSONResponse({**safe_error(ProductError("invalid_input")),
                             "notice": service.notices.current()}, status_code=422)

    def principal(request: Request) -> Principal:
        authorization = request.headers.get("authorization", "")
        token = authorization.removeprefix("Bearer ") if authorization.startswith("Bearer ") else request.cookies.get("dtv_session")
        return service.directory.resolve(token)

    @app.get("/")
    @app.get("/review/{sid}")
    def editor(request: Request, sid: str | None = None):
        return templates.TemplateResponse(request=request, name="editor.html", context={
            "notice": service.notices.current(), "simulated": service.classifier.simulated,
            "local_sessions": local_sessions, "submission_id": sid or ""})

    if local_sessions:
        @app.post("/local/session")
        def local_session(body: SessionRequest, response: Response):
            token = service.directory.issue_local(body.identity)
            response.set_cookie("dtv_session", token, httponly=True, samesite="strict", secure=False)
            return {"identity": body.identity, "synthetic": True}

        @app.post("/local/work")
        def local_work(actor: Principal = Depends(principal)):
            # Synthetic operator identity is independently onboarded. No live-mode worker route.
            from .onboarding import MATERIAL_VERSIONS
            operator = service.directory.current("synthetic-operator")
            service.onboarding.require(operator)
            service.authorize(actor, "editor", "admin")
            return {"processed": run_one(service), "operator_material": MATERIAL_VERSIONS["operator"]}

    @app.get("/materials/{role}", response_class=PlainTextResponse)
    def material(role: str):
        names = {"editor": "editors", "admin": "admins", "operator": "operators"}
        if role not in names:
            raise ProductError("not_found", 404)
        return (ROOT.parent / "training" / (names[role] + ".md")).read_text()

    @app.post("/api/submissions", status_code=202)
    def submit(body: SubmissionRequest, idempotency_key: str = Header(), actor: Principal = Depends(principal)):
        return service.submit(actor, [body], idempotency_key)[0]

    @app.post("/api/batches", status_code=202)
    def batch(body: BatchRequest, idempotency_key: str = Header(), actor: Principal = Depends(principal)):
        return {"items": service.submit(actor, body.items, idempotency_key, "batch")}

    @app.get("/api/submissions/{sid}")
    def read(sid: str, purpose: str = Query(), actor: Principal = Depends(principal)):
        return service.read(actor, sid, purpose)

    @app.get("/api/submissions/{sid}/export")
    def export(sid: str, purpose: str = Query(), actor: Principal = Depends(principal)):
        envelope = service.read(actor, sid, purpose)
        return Response(export_advice(envelope), media_type="application/json",
                        headers={"Content-Disposition": 'attachment; filename="editorial-advice.json"'})

    @app.post("/api/submissions/{sid}/retry")
    def retry(sid: str, purpose: str = Query(), actor: Principal = Depends(principal)):
        return service.retry(actor, sid, purpose)

    @app.post("/api/submissions/{sid}/review")
    def judge(sid: str, body: ReviewRequest, purpose: str = Query(), actor: Principal = Depends(principal)):
        return service.judge(actor, sid, purpose, body.decision)

    @app.delete("/api/submissions/{sid}")
    def delete(sid: str, actor: Principal = Depends(principal)):
        return service.delete(actor, sid)

    return app

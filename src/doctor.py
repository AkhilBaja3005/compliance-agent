"""`aegis doctor`: verify every integration and report OK / FAIL / SKIP with the reason. Secrets are never printed.

Configuration checks run always. `live=True` also makes one small read-only call per configured service (Linkup search, Atlas ping +
vector-index status, Databricks endpoint lookup, GitHub /user, Confluence spaces). A service whose variables are unset is SKIP
(runs on its offline fallback), never FAIL.
"""
from __future__ import annotations

import importlib
import os
import sys
from dataclasses import dataclass


@dataclass
class Check:
    name: str
    status: str  # OK | FAIL | SKIP | WARN
    detail: str


def _env(*names: str) -> str | None:
    return next((os.environ[n] for n in names if os.environ.get(n)), None)


def _safe(fn) -> tuple[str, str]:
    try:
        return fn()
    except Exception as exc:  # message only: exception text can echo URLs, never tokens we pass in headers
        return "FAIL", f"{type(exc).__name__}: {str(exc)[:140]}"


def run_checks(live: bool = False, http_client=None) -> list[Check]:
    out: list[Check] = []

    def add(name, fn):
        s, d = _safe(fn)
        out.append(Check(name, s, d))

    add("python", lambda: ("OK", sys.version.split()[0]) if sys.version_info >= (3, 11) else ("FAIL", f"{sys.version.split()[0]} (need >= 3.11)"))

    def grammars():
        from src.edge_extractors.lang_scanner import LANGS, _parser
        bad = sorted({l for l, _ in LANGS.values() if _parser(l) is None})
        return ("OK", f"{len({l for l, _ in LANGS.values()})} tree-sitter grammars loaded") if not bad else ("FAIL", "missing grammars: " + ", ".join(bad))
    add("code parsers", grammars)

    def libs():
        missing = [m for m in ("docx", "openpyxl", "pptx", "pyarrow", "yaml", "bs4", "pypdf") if importlib.util.find_spec(m) is None]
        return ("OK", "document/data readers installed") if not missing else ("FAIL", "missing: " + ", ".join(missing))
    add("document + data readers", libs)

    def ocr():
        have = importlib.util.find_spec("pytesseract") and importlib.util.find_spec("pypdfium2")
        return ("OK", "pytesseract + pypdfium2 present (needs the tesseract binary on PATH)") if have else ("WARN", "OCR not installed: scanned PDFs become OCR_REQUIRED gaps")
    add("OCR", ocr)

    def pdf():
        importlib.import_module("weasyprint")
        return "OK", "WeasyPrint importable"
    add("PDF renderer", pdf)

    def rules():
        from src.law_sync import get_store
        n = len(get_store().snapshot())
        return ("OK", f"{n} rules, version {get_store().version}") if n >= 20 else ("FAIL", f"only {n} rules")
    add("rule library", rules)

    def auth():
        if os.getenv("AEGIS_AUTH_DISABLED", "").lower() == "true":
            return "WARN", "AEGIS_AUTH_DISABLED=true: API is open (development only)"
        from src import security
        n = len(security._load_keys())
        return ("OK", f"{n} API key(s) configured") if n else ("FAIL", "AEGIS_API_KEYS not set: the API refuses all requests")
    add("API auth", auth)

    def data_dir():
        d = os.getenv("AEGIS_DATA_DIR")
        if not d:
            return "WARN", "AEGIS_DATA_DIR unset: jobs, reports and sign-offs are kept in memory only"
        os.makedirs(d, exist_ok=True)
        probe = os.path.join(d, ".doctor")
        open(probe, "w").close()
        os.remove(probe)
        return "OK", f"{d} writable"
    add("data directory", data_dir)

    # ---- Linkup
    def linkup():
        if not os.getenv("LINKUP_API_KEY"):
            return "SKIP", "LINKUP_API_KEY unset (no live citations; seed rules only)"
        if not live:
            return "OK", "key present (use --live to test a search)"
        from linkup import LinkupClient
        r = LinkupClient().search(query="EU AI Act Article 5 prohibited practices", depth="standard", output_type="sourcedAnswer")
        n = len(getattr(r, "sources", []) or [])
        return ("OK", f"search returned {n} source(s)") if n else ("WARN", "search worked but returned no sources")
    add("Linkup", linkup)

    # ---- MongoDB Atlas
    def mongo():
        uri = os.getenv("MONGODB_URI")
        if not uri:
            return "SKIP", "MONGODB_URI unset (in-memory store + local BM25 fallback)"
        if not live:
            return "OK", "URI present (use --live to ping and check vector indexes)"
        from pymongo import MongoClient
        c = MongoClient(uri, serverSelectionTimeoutMS=5000)
        c.admin.command("ping")
        db = c[_env("MONGODB_DATABASE", "MONGODB_DB_NAME") or "aegis_compliance"]
        msgs, bad = [], False
        for coll in ("regulatory_rules", "tenant_artifacts"):
            try:
                idx = list(db[coll].list_search_indexes())
            except Exception:
                idx = []
            states = [f"{i.get('name')}={i.get('status', '?')}" for i in idx]
            bad |= not any(i.get("queryable") for i in idx)
            msgs.append(f"{coll}: {', '.join(states) or 'no vector index yet (run aegis sync-laws; builds take ~1 min)'}")
        return ("WARN" if bad else "OK"), "ping ok; " + "; ".join(msgs)
    add("MongoDB Atlas", mongo)

    # ---- Databricks
    def databricks():
        host, tok, ep = os.getenv("DATABRICKS_HOST"), os.getenv("DATABRICKS_TOKEN"), os.getenv("DATABRICKS_SERVING_ENDPOINT")
        if not (host and tok):
            return "SKIP", "DATABRICKS_HOST/TOKEN unset (deterministic offline narratives)"
        if not ep:
            return "WARN", "host/token set but DATABRICKS_SERVING_ENDPOINT unset"
        if not live:
            return "OK", f"endpoint {ep} configured (use --live to look it up)"
        from databricks.sdk import WorkspaceClient
        w = WorkspaceClient(host=host, token=tok)
        e = w.serving_endpoints.get(ep)
        ready = getattr(getattr(e, "state", None), "ready", None)
        return ("OK" if str(ready).endswith("READY") else "WARN"), f"endpoint {ep} state={ready}"
    add("Databricks Model Serving", databricks)

    def uc():
        if not os.getenv("DATABRICKS_WAREHOUSE_ID"):
            return "SKIP", "DATABRICKS_WAREHOUSE_ID unset (Unity Catalog persistence disabled)"
        return "OK", "warehouse id configured (writes happen at audit time)"
    add("Unity Catalog", uc)

    def mlflow():
        uri = os.getenv("MLFLOW_TRACKING_URI")
        if not uri:
            return "SKIP", "MLFLOW_TRACKING_URI unset (tracing is a no-op)"
        if importlib.util.find_spec("mlflow") is None:
            return "FAIL", "mlflow not installed"
        return "OK", f"tracking uri {uri.split('@')[-1][:60]}"
    add("MLflow", mlflow)

    # ---- connectors (live calls use httpx; tokens go in headers only)
    def github():
        tok = os.getenv("GITHUB_TOKEN")
        if not tok:
            return "SKIP", "GITHUB_TOKEN unset (public repos and local folders only)"
        if not live:
            return "OK", "token present (use --live to verify)"
        import httpx
        r = (http_client or httpx).get("https://api.github.com/user", headers={"Authorization": f"Bearer {tok}"}, timeout=15)
        return ("OK", f"authenticated, rate remaining {r.headers.get('x-ratelimit-remaining', '?')}") if r.status_code == 200 else ("FAIL", f"HTTP {r.status_code}")
    add("GitHub", github)

    def confluence():
        url, user, tok = os.getenv("CONFLUENCE_URL"), _env("CONFLUENCE_EMAIL", "CONFLUENCE_USERNAME"), os.getenv("CONFLUENCE_API_TOKEN")
        if not (url and user and tok):
            return "SKIP", "CONFLUENCE_* unset (local exports only)"
        if not live:
            return "OK", "credentials present (use --live to verify)"
        import httpx
        r = (http_client or httpx).get(url.rstrip("/") + "/api/v2/spaces", params={"limit": 1}, auth=(user, tok), timeout=15)
        return ("OK", "spaces readable") if r.status_code == 200 else ("FAIL", f"HTTP {r.status_code}")
    add("Confluence", confluence)

    def remote_docs():
        on = os.getenv("AEGIS_REMOTE_DOC_SOURCES", "").lower() == "true"
        from src.connectors.doc_sources import sources_from_env
        names = [s.name for s in sources_from_env()] if on else []
        return ("OK", "enabled: " + ", ".join(names)) if names else ("SKIP", "AEGIS_REMOTE_DOC_SOURCES not enabled")
    add("Remote doc sources", remote_docs)
    return out


def exit_code(checks: list[Check]) -> int:
    return 1 if any(c.status == "FAIL" for c in checks) else 0

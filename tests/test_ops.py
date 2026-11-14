"""Operational commands: doctor (config + live with fakes), demo, observability."""
from __future__ import annotations

import json
import logging

from typer.testing import CliRunner

from src.doctor import exit_code, run_checks
from src.observability import JsonFormatter, Metrics, request_id_var


def _by(checks):
    return {c.name: c for c in checks}


def test_doctor_config_mode_never_fails_on_unset_services(monkeypatch):
    for v in ("LINKUP_API_KEY", "MONGODB_URI", "DATABRICKS_HOST", "DATABRICKS_TOKEN", "GITHUB_TOKEN", "CONFLUENCE_URL", "MLFLOW_TRACKING_URI"):
        monkeypatch.delenv(v, raising=False)
    monkeypatch.setenv("AEGIS_AUTH_DISABLED", "false")
    monkeypatch.delenv("AEGIS_API_KEYS", raising=False)
    c = _by(run_checks())
    assert c["Linkup"].status == "SKIP" and c["MongoDB Atlas"].status == "SKIP" and c["Databricks Model Serving"].status == "SKIP"
    assert c["code parsers"].status == "OK" and c["rule library"].status == "OK"
    assert c["API auth"].status == "FAIL" and exit_code(list(c.values())) == 1  # closed API is a failure the operator must see
    monkeypatch.setenv("AEGIS_API_KEYS", "k-123456:*:admin")
    assert _by(run_checks())["API auth"].status == "OK"


def test_doctor_live_github_uses_header_only_and_hides_token(monkeypatch):
    seen = {}

    class R:
        status_code = 200
        headers = {"x-ratelimit-remaining": "4999"}

    class Http:
        @staticmethod
        def get(url, headers=None, **kw):
            seen["url"], seen["auth"] = url, headers["Authorization"]
            return R()
    monkeypatch.setenv("GITHUB_TOKEN", "ghp_supersecrettoken")
    c = _by(run_checks(live=True, http_client=Http))["GitHub"]
    assert c.status == "OK" and seen["url"] == "https://api.github.com/user" and "ghp_supersecrettoken" not in c.detail


def test_doctor_cli_exit_code(monkeypatch):
    from aegis_audit.cli import app
    monkeypatch.setenv("AEGIS_AUTH_DISABLED", "false")
    monkeypatch.delenv("AEGIS_API_KEYS", raising=False)
    res = CliRunner().invoke(app, ["doctor"])
    assert res.exit_code == 1 and "API auth" in res.output


def test_demo_writes_pdfs_and_summary(tmp_path):
    from aegis_audit.cli import app
    res = CliRunner().invoke(app, ["demo", "--out-dir", str(tmp_path)])
    assert res.exit_code == 0, res.output
    summary = json.loads((tmp_path / "summary.json").read_text())
    assert len(summary) == 3 and all((tmp_path / f"{s['pdf'].split('/')[-1]}").exists() for s in summary)
    assert {s["company"] for s in summary} == {"Aegis Health UK", "Meridian OmniTech", "Veylan Analytics"}


def test_json_logs_carry_request_id_and_metrics_render():
    request_id_var.set("req-1")
    rec = logging.LogRecord("aegis.api", logging.INFO, "f", 1, "request", (), None)
    rec.status = 200
    d = json.loads(JsonFormatter().format(rec))
    assert d["request_id"] == "req-1" and d["status"] == 200 and d["level"] == "INFO"
    m = Metrics()
    m.inc("aegis_x_total", status=200)
    m.inc("aegis_x_total", status=200)
    assert 'aegis_x_total{status="200"} 2' in m.render()


def test_default_scan_target_returns_a_session_and_pdf(tmp_path):
    """Regression: `aegis scan` with no target must audit the bundled demo data, not return None."""
    from aegis_audit.client import ComplianceAuditor
    s = ComplianceAuditor().audit()
    assert s is not None and s.company_name
    assert (tmp_path / "x.pdf").parent.exists() and s.save_pdf(str(tmp_path / "x.pdf")).endswith("x.pdf")

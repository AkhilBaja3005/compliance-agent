"""API hardening: closed by default, roles, tenant isolation, rate limits, size limits, SSRF/path guards, jobs, sign-off, logging hygiene."""
from __future__ import annotations

import logging
import threading

import pytest
from fastapi.testclient import TestClient

from src import api, security as sec
from src.jobs import JobManager, ReportStore
from src.observability import metrics

KEYS = "adminkey-0001:*:admin,auditorA-0002:company_a_finscore:auditor,auditorB-0003:company_b_voxgen:auditor,viewerA-0004:company_a_finscore:viewer"
H = lambda k: {"Authorization": f"Bearer {k}"}


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setenv("AEGIS_AUTH_DISABLED", "false")
    monkeypatch.setenv("AEGIS_API_KEYS", KEYS)
    sec.limiter.reset()
    metrics.reset()
    api.init_state(force=True)
    with TestClient(api.app) as c:
        yield c


def test_closed_by_default_without_keys(monkeypatch):
    monkeypatch.setenv("AEGIS_AUTH_DISABLED", "false")
    monkeypatch.delenv("AEGIS_API_KEYS", raising=False)
    with TestClient(api.app) as c:
        assert c.get("/companies").status_code == 503
        assert c.get("/healthz").status_code == 200
        assert c.get("/readyz").status_code == 503  # auth not configured is not "ready"


def test_missing_and_wrong_key_rejected(client):
    assert client.get("/companies").status_code == 401
    assert client.get("/companies", headers=H("nope")).status_code == 401
    assert client.get("/companies", headers={"X-API-Key": "adminkey-0001"}).status_code == 200


def test_roles_and_tenant_scoping(client):
    names = {c["company_id"] for c in client.get("/companies", headers=H("viewerA-0004")).json()}
    assert names == {"company_a_finscore"}  # list is filtered to the key's tenants
    assert client.post("/audit/run", json={"company_id": "company_a_finscore"}, headers=H("viewerA-0004")).status_code == 403
    assert client.post("/audit/run", json={"company_id": "company_b_voxgen"}, headers=H("auditorA-0002")).status_code == 403
    assert client.post("/laws/sync", headers=H("auditorA-0002")).status_code == 403
    assert client.get("/stack/status", headers=H("auditorA-0002")).status_code == 403
    assert client.get("/metrics", headers=H("adminkey-0001")).status_code == 200
    assert client.get("/metrics", headers=H("viewerA-0004")).status_code == 403


def test_security_headers_and_request_id(client):
    r = client.get("/healthz", headers={"X-Request-ID": "abc123"})
    assert r.headers["X-Request-ID"] == "abc123" and r.headers["X-Content-Type-Options"] == "nosniff"
    assert r.headers["Cache-Control"] == "no-store" and "frame-ancestors 'none'" in r.headers["Content-Security-Policy"]


def test_rate_limit_on_heavy_endpoint(client, monkeypatch):
    monkeypatch.setenv("AEGIS_RATE_LIMIT_HEAVY_PER_MIN", "2")
    body = {"company_id": "company_a_finscore"}
    codes = [client.post("/audit/jobs", json=body, headers={**H("auditorA-0002"), "Idempotency-Key": f"k{i}"}).status_code for i in range(3)]
    assert codes[:2] == [202, 202] and codes[2] == 429
    r = client.post("/audit/jobs", json=body, headers=H("auditorA-0002"))
    assert r.status_code == 429 and int(r.headers["Retry-After"]) >= 1


def test_body_size_limit(client, monkeypatch):
    monkeypatch.setenv("AEGIS_MAX_BODY_BYTES", "50")
    r = client.post("/audit/run", json={"company_id": "company_a_finscore", "github_url": "https://github.com/" + "x" * 100}, headers=H("auditorA-0002"))
    assert r.status_code == 413


@pytest.mark.parametrize("url", ["http://github.com/o/r", "https://evil.example.com/o/r", "file:///etc/passwd", "git@github.com:o/r.git",
                                 "https://user:pw@github.com/o/r", "https://169.254.169.254/latest"])
def test_repo_url_ssrf_guard(client, url):
    r = client.post("/audit/run", json={"company_id": "company_a_finscore", "github_url": url}, headers=H("adminkey-0001"))
    assert r.status_code == 400, url


def test_local_paths_are_admin_only_and_confined(client, tmp_path):
    body = {"company_id": "company_a_finscore", "confluence_path": "/etc"}
    assert client.post("/audit/run", json=body, headers=H("auditorA-0002")).status_code == 403
    assert client.post("/audit/run", json=body, headers=H("adminkey-0001")).status_code == 400  # outside the companies root


def test_ingest_pdf_confined_to_pdf_root(client, monkeypatch, tmp_path):
    monkeypatch.setenv("AEGIS_PDF_ROOT", str(tmp_path))
    outside = client.post("/admin/ingest-pdf", json={"pdf_path": "/etc/hosts"}, headers=H("adminkey-0001"))
    assert outside.status_code == 400
    assert client.post("/admin/ingest-pdf", json={"pdf_path": str(tmp_path / "x.pdf")}, headers=H("auditorA-0002")).status_code == 403


def test_job_lifecycle_idempotency_and_tenant_isolation(client):
    h = {**H("auditorA-0002"), "Idempotency-Key": "once"}
    r1 = client.post("/audit/jobs", json={"company_id": "company_a_finscore"}, headers=h)
    r2 = client.post("/audit/jobs", json={"company_id": "company_a_finscore"}, headers=h)
    assert r1.status_code == 202 and r2.status_code == 200 and r1.json()["job_id"] == r2.json()["job_id"]
    jid = r1.json()["job_id"]
    api.state.jobs.wait(jid, 60)
    st = client.get(f"/audit/jobs/{jid}", headers=H("viewerA-0004")).json()
    assert st["status"] == "succeeded" and "params" not in st
    rep = client.get(f"/audit/jobs/{jid}/report", headers=H("viewerA-0004")).json()
    assert rep["company_name"] and rep["report_id"] == st["report_id"]
    assert client.get(f"/audit/jobs/{jid}", headers=H("auditorB-0003")).status_code == 404  # other tenant cannot even see it exists
    assert client.get(f"/reports/{st['report_id']}", headers=H("auditorB-0003")).status_code == 404
    assert client.get(f"/reports/{st['report_id']}", headers=H("viewerA-0004")).status_code == 200
    assert 'aegis_audits_total{tenant="company_a_finscore"}' in metrics.render()


def test_job_cancel_timeout_and_failure_isolated():
    gate = threading.Event()
    calls = []

    def run(params):
        calls.append(params["n"])
        if params["n"] == "block":
            gate.wait(5)
        if params["n"] == "boom":
            raise RuntimeError("bad repo")
        return {"report_id": f"R-{params['n']}"}
    jm = JobManager(run, ReportStore(None), workers=1, timeout_s=0.2)
    block, _ = jm.submit("t", {"n": "block"}, "o")
    queued, _ = jm.submit("t", {"n": "queued"}, "o")
    assert jm.cancel(queued.job_id).status == "cancelled"
    assert jm.wait(block.job_id, 3).status == "timed_out"  # watchdog marks it; thread result is discarded
    gate.set()
    boom, _ = jm.submit("t", {"n": "boom"}, "o")
    ok, _ = jm.submit("t", {"n": "ok"}, "o")
    assert jm.wait(boom.job_id).status == "failed" and "bad repo" in jm.get(boom.job_id).error
    assert jm.wait(ok.job_id).status == "succeeded"  # one failing job does not poison the pool
    assert "queued" not in calls


def test_jobs_persist_and_unfinished_become_interrupted(tmp_path):
    jm = JobManager(lambda p: {"report_id": "R1"}, ReportStore(tmp_path), workers=1, data_dir=tmp_path)
    j, _ = jm.submit("t", {}, "o", "key1")
    jm.wait(j.job_id)
    # simulate a crash: a job left running in the file
    import json
    f = tmp_path / "jobs.json"
    d = json.loads(f.read_text())
    d[0]["status"] = "running"
    f.write_text(json.dumps(d))
    jm2 = JobManager(lambda p: {"report_id": "R2"}, ReportStore(tmp_path), workers=1, data_dir=tmp_path)
    assert jm2.get(j.job_id).status == "interrupted"
    assert jm2.submit("t", {}, "o", "key1")[0].job_id == j.job_id  # idempotency survives the restart


def test_signoff_flow_and_tamper_evidence(client):
    jid = client.post("/audit/jobs", json={"company_id": "company_a_finscore"}, headers=H("auditorA-0002")).json()["job_id"]
    api.state.jobs.wait(jid, 60)
    rid = api.state.jobs.get(jid).report_id
    fid = client.get(f"/reports/{rid}", headers=H("auditorA-0002")).json()["confirmed_findings"][0]["finding_id"]
    assert client.post(f"/reports/{rid}/signoff", json={"decision": "approve", "reviewer_name": "R"}, headers=H("viewerA-0004")).status_code == 403
    assert client.post(f"/reports/{rid}/signoff", json={"decision": "maybe", "reviewer_name": "R"}, headers=H("auditorA-0002")).status_code == 422
    assert client.post(f"/reports/{rid}/signoff", json={"decision": "approve", "reviewer_name": "R", "finding_id": "nope"}, headers=H("auditorA-0002")).status_code == 404
    assert client.post(f"/reports/{rid}/signoff", json={"decision": "approve", "reviewer_name": "Ada, Head of AI Governance", "finding_id": fid, "note": "verified"}, headers=H("auditorA-0002")).status_code == 201
    assert client.post(f"/reports/{rid}/signoff", json={"decision": "needs_info", "reviewer_name": "Ada"}, headers=H("auditorA-0002")).status_code == 201
    st = client.get(f"/reports/{rid}/signoff", headers=H("viewerA-0004")).json()
    assert st["chain_valid"] and st["status"]["findings"][fid] == "approve" and st["status"]["report_decision"] == "needs_info"
    assert st["records"][0]["reviewer_key_id"] == sec.key_id("auditorA-0002")
    api.state.signoffs._records[0]["decision"] = "reject"  # tamper
    assert api.state.signoffs.verify() == (False, 1)


def test_api_keys_never_appear_in_logs(client, caplog):
    caplog.set_level(logging.INFO, logger="aegis")
    api.log.propagate = True
    logging.getLogger("aegis").propagate = True
    client.get("/companies", headers=H("viewerA-0004"))
    client.get("/companies", headers=H("wrong-secret-key"))
    text = "\n".join(r.getMessage() + str(getattr(r, "key_id", "")) for r in caplog.records)
    assert "viewerA-0004" not in text and "wrong-secret-key" not in text
    assert sec.key_id("viewerA-0004") in text


def test_rate_limiter_window_math():
    rl = sec.RateLimiter()
    assert [rl.check("k", 2, 60, now=t) for t in (0, 1)] == [None, None]
    assert rl.check("k", 2, 60, now=2) == pytest.approx(58)
    assert rl.check("k", 2, 60, now=61) is None


def test_rule_review_gate_stages_then_approves(client, monkeypatch):
    monkeypatch.setenv("AEGIS_RULE_REVIEW_REQUIRED", "true")
    before = client.get("/laws/status", headers=H("viewerA-0004")).json()["law_index_version"]
    r = client.post("/laws/simulate-update", json={"jurisdiction": "EU_AI_ACT", "title": "Art. 50 amendment", "text": "Amended transparency text."}, headers=H("adminkey-0001")).json()
    assert r["changed"] is False and any("STAGED" in l for l in r["log"])
    assert client.get("/laws/status", headers=H("viewerA-0004")).json()["law_index_version"] == before  # live library untouched
    pend = client.get("/laws/pending", headers=H("adminkey-0001")).json()
    assert len(pend) == 1 and client.get("/laws/pending", headers=H("auditorA-0002")).status_code == 403
    ap = client.post(f"/laws/pending/{pend[0]['pending_id']}/approve", params={"reviewer_name": "Counsel"}, headers=H("adminkey-0001"))
    assert ap.status_code == 200 and ap.json()["changed"] is True and ap.json()["new_version"] != before
    assert client.post("/laws/pending/nope/reject", headers=H("adminkey-0001")).status_code == 404


def test_laws_ingest_is_admin_only_and_takes_no_paths(client, tmp_path, monkeypatch):
    (tmp_path / "x.md").write_text("# X\nRecord keeping obligations require logs of events over the system lifetime.\n")
    (tmp_path / "s.yaml").write_text(f"folders:\n  - path: {tmp_path}\n")
    monkeypatch.setenv("AEGIS_SYNC_CONFIG", str(tmp_path / "s.yaml"))
    assert client.post("/laws/ingest", headers=H("auditorA-0002")).status_code == 403
    r = client.post("/laws/ingest", params={"deep_linkup": "false"}, json={"folders": ["/etc"], "urls": ["https://evil.example"]}, headers=H("adminkey-0001"))
    assert r.status_code == 200 and [s["source"].split("/")[-1] for s in r.json()["sources"]] == ["x.md"]  # request body cannot add sources

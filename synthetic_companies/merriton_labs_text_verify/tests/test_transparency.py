from dataclasses import replace
from app.notices import Notice
from app.worker import run_one

PURPOSE = "?purpose=business_editorial_review"


def test_notice_before_submission_and_direct_navigation(system):
    for route in ("/", "/review/nonexistent"):
        page = system.client.get(route)
        assert page.status_code == 200
        assert page.text.index('id="ai-notice"') < page.text.index('id="submission-form"')
        assert 'id="submit" type="submit" disabled' in page.text
        assert "notice-2" in page.text
        assert "deterministic simulation, not a validated detector" in page.text
        assert "aria-live=\"polite\"" in page.text
    # Real keyboard, assistive-technology and perceptual checks remain external.


def test_updated_notice_and_limitations_on_every_delivery(system):
    s, actor, client = system.service, system.actor, system.client
    sid = s.submit(actor, [system.request], "notice-request")[0]["id"]
    run_one(s)
    original_output = s.storage.get(actor.tenant, sid).output.model_dump()
    s.notices.history["notice-3-test"] = Notice("notice-3-test", "Updated synthetic AI interaction notice.")
    s.notices.active = "notice-3-test"
    model = s.registry.models["dtv-1.1"]
    s.registry.models[model.version] = replace(model, limitations=model.limitations + ("New synthetic release warning.",))
    assert "Updated synthetic AI interaction notice." in client.get("/review/" + sid).text
    paths = ["/api/submissions/" + sid + PURPOSE,
             "/api/submissions/" + sid + "/export" + PURPOSE]
    envelopes = [client.get(path).json() for path in paths]
    envelopes.append(client.post("/api/submissions", json=system.request.model_dump(),
                                 headers={"Idempotency-Key": "notice-request"}).json())
    envelopes.append(client.post("/api/submissions/" + sid + "/review" + PURPOSE,
                                 json={"decision": "dismiss_flag"}).json())
    envelopes.append(client.post("/api/submissions/" + sid + "/retry" + PURPOSE).json())
    cached_id = s.submit(actor, [system.request], "notice-new-key")[0]["id"]
    run_one(s)
    envelopes.append(client.get("/api/submissions/" + cached_id + PURPOSE).json())
    for envelope in envelopes:
        assert envelope["notice"]["version"] == "notice-3-test"
        assert "New synthetic release warning." in envelope["limitations"]
        assert all(warning in envelope["limitations"] for warning in model.limitations)
        assert envelope["analysis"] == original_output
    assert envelopes[0]["submitted_notice_version"] == "notice-2"
    assert s.classifier.calls == 1
    bad = client.get("/api/submissions/" + sid + "?purpose=recruitment")
    assert bad.status_code == 422
    assert bad.json()["notice"]["version"] == "notice-3-test"


def test_notice_remains_on_error_and_retry(system):
    s, client = system.service, system.client
    s.classifier.failure = "provider_timeout"
    sid = s.submit(system.actor, [system.request], "retry-notice")[0]["id"]
    run_one(s)
    assert "notice-2" in client.get("/review/" + sid).text
    failed = client.get("/api/submissions/" + sid + PURPOSE).json()
    assert failed["state"] == "failed" and failed["analysis"] is None
    retry = client.post("/api/submissions/" + sid + "/retry" + PURPOSE).json()
    assert retry["notice"]["version"] == "notice-2"
    assert retry["state"] == "queued"
    invalid = client.post("/api/submissions", json={"text": "PRIVATE RAW INPUT"},
                          headers={"Idempotency-Key": "invalid-key"})
    assert invalid.status_code == 422
    assert "PRIVATE RAW INPUT" not in invalid.text
    assert "notice-2" in invalid.text


def test_judgment_is_separate_from_analysis(system):
    s = system.service
    sid = s.submit(system.actor, [system.request], "judge-request")[0]["id"]
    run_one(s)
    before = s.read(system.actor, sid, system.request.purpose)
    after = s.judge(system.actor, sid, system.request.purpose, "dismiss_flag")
    assert before["analysis"] == after["analysis"]
    assert after["editorial_judgment"]["kind"] == "human_editorial_judgment"
    assert after["editorial_judgment"]["decision"] == "dismiss_flag"
    assert "not a verdict" in after["advice"]

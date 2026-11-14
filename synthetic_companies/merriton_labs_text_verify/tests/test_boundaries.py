from dataclasses import replace
import pytest
from app.domain import Job
from app.errors import ProductError
from app.onboarding import MATERIAL_VERSIONS
from app.worker import run_one


@pytest.mark.parametrize("purpose", ["recruitment", "education", "grading", "misconduct",
                                    "employee_evaluation", "eligibility", "reputation", "other"])
def test_purposes_rejected_before_any_side_effect(system, purpose):
    s = system.service
    bad = system.request.model_copy(update={"purpose": purpose})
    with pytest.raises(ProductError) as error:
        s.submit(system.actor, [bad], "bad-purpose-key")
    assert (error.value.code, error.value.status) == ("purpose_rejected", 422)
    assert s.classifier.calls == 0
    assert not s.storage.records and not s.storage.cache and not s.jobs.pending
    assert not s.storage.idempotency and not s.audit.events


def test_batch_validates_all_items_first(system):
    bad = system.request.model_copy(update={"purpose": "recruitment"})
    response = system.client.post("/api/batches", json={"items": [system.request.model_dump(), bad.model_dump()]},
                                  headers={"Idempotency-Key": "batch-rejected"})
    assert response.status_code == 422
    assert not system.service.storage.records and not system.service.jobs.pending


def test_tenant_isolation_across_delivery_and_mutation(system):
    s, client = system.service, system.client
    sid = s.submit(system.actor, [system.request], "tenant-request")[0]["id"]
    birch = s.directory.current("birch-editor")
    client.headers["Authorization"] = "Bearer " + s.directory.issue_local(birch.subject)
    prefix = "/api/submissions/" + sid
    purpose = "?purpose=business_editorial_review"
    for method, path, body in [("GET", prefix + purpose, None),
                               ("GET", prefix + "/export" + purpose, None),
                               ("POST", prefix + "/retry" + purpose, None),
                               ("POST", prefix + "/review" + purpose, {"decision": "retain_flag"}),
                               ("DELETE", prefix, None)]:
        response = client.request(method, path, json=body)
        assert response.status_code == 404
        assert response.json()["code"] == "not_found"
    s.process(Job("birch", sid, 1))
    assert s.classifier.calls == 0
    assert s.storage.get("atlas", sid).state == "queued"


def test_cache_is_tenant_and_model_scoped(system):
    s = system.service
    one = s.submit(system.actor, [system.request], "cache-atlas")[0]["id"]
    run_one(s)
    birch = s.directory.current("birch-editor")
    two = s.submit(birch, [system.request], "cache-birch")[0]["id"]
    run_one(s)
    other = system.request.model_copy(update={"model_version": "dtv-1.0"})
    three = s.submit(system.actor, [other], "cache-version")[0]["id"]
    run_one(s)
    keys = {s.storage.get("atlas", one).cache_key, s.storage.get("birch", two).cache_key,
            s.storage.get("atlas", three).cache_key}
    assert len(keys) == 3 and s.classifier.calls == 3


def test_cache_does_not_bypass_current_policy(system):
    s = system.service
    sid = s.submit(system.actor, [system.request], "warm-cache-key")[0]["id"]
    run_one(s)
    with pytest.raises(ProductError, match="purpose_rejected"):
        s.read(system.actor, sid, "recruitment")
    bad = system.request.model_copy(update={"purpose": "recruitment"})
    with pytest.raises(ProductError, match="purpose_rejected"):
        s.submit(system.actor, [bad], "bad-cached-key")
    queued = s.submit(system.actor, [system.request], "queued-cache-key")[0]["id"]
    s.onboarding.records = [r for r in s.onboarding.records if r["subject"] != system.actor.subject]
    run_one(s)
    assert s.storage.get("atlas", queued).error_code == "forbidden"
    assert s.classifier.calls == 1
    s.directory.people[system.actor.subject] = replace(system.actor, tenant="birch")
    with pytest.raises(ProductError, match="forbidden"):
        s.read(system.actor, sid, system.request.purpose)


def test_model_compatibility_and_withdrawal(system):
    s = system.service
    incompatible = system.request.model_copy(update={"model_version": "dtv-1.0", "domain": "business_article"})
    with pytest.raises(ProductError, match="model_unavailable"):
        s.submit(system.actor, [incompatible], "model-mismatch")
    sid = s.submit(system.actor, [system.request], "withdraw-model")[0]["id"]
    s.registry.withdrawn.add("dtv-1.1")
    run_one(s)
    assert s.storage.get("atlas", sid).error_code == "model_unavailable"
    with pytest.raises(ProductError, match="model_unavailable"):
        s.read(system.actor, sid, system.request.purpose)
    with pytest.raises(ProductError, match="model_unavailable"):
        s.submit(system.actor, [system.request], "withdraw-model")
    assert s.classifier.calls == 0
    assert s.delete(system.actor, sid)["state"] == "deleted"


def test_role_specific_onboarding_records_and_gate(system):
    s = system.service
    for role, subject in [("editor", "atlas-editor"), ("admin", "birch-admin"), ("operator", "synthetic-operator")]:
        principal = s.directory.current(subject)
        s.onboarding.require(principal)
        record = next(r for r in s.onboarding.records if r["subject"] == subject)
        assert record["synthetic"] is True and record["material_version"] == MATERIAL_VERSIONS[role]
    s.onboarding.records.clear()
    with pytest.raises(ProductError, match="forbidden"):
        s.submit(system.actor, [system.request], "not-onboarded")
    with pytest.raises(ProductError, match="forbidden"):
        run_one(s)
    assert s.classifier.calls == 0

import io
import json
import pytest
from botocore.exceptions import ReadTimeoutError
from app.domain import Job
from app.errors import ProductError, ProviderFailure
from app.sagemaker import SageMakerClassifier
from app.sqs import SqsQueue
from app.schemas import ClassifierOutput
from app.worker import run_one


@pytest.mark.parametrize("text_name,language,reason,calls", [
    ("short", "en", "low_confidence", 1),
    ("unsupported_language", "fr", "unsupported_language", 0)])
def test_abstention_has_no_score(system, text_name, language, reason, calls):
    request = system.request.model_copy(update={"text": system.texts[text_name], "language": language})
    sid = system.service.submit(system.actor, [request], "abstain-request")[0]["id"]
    run_one(system.service)
    result = system.service.read(system.actor, sid, request.purpose)
    assert result["state"] == "abstained" and result["analysis"]["score"] is None
    assert result["analysis"]["reason"] == reason and result["limitations"]
    assert system.service.classifier.calls == calls


def test_provider_timeout_is_not_an_answer(system):
    s = system.service
    s.classifier.failure = "provider_timeout"
    sid = s.submit(system.actor, [system.request], "timeout-request")[0]["id"]
    for attempt in (1, 2, 3):
        run_one(s)
        result = s.read(system.actor, sid, system.request.purpose)
        assert result["state"] == "failed" and result["analysis"] is None
        assert result["error_code"] == "provider_timeout" and result["attempt"] == attempt
        assert not s.storage.cache
        if attempt < 3:
            s.retry(system.actor, sid, system.request.purpose)
    with pytest.raises(ProductError):
        s.retry(system.actor, sid, system.request.purpose)
    assert s.classifier.calls == 3
    assert all(system.request.text not in repr(e) for e in s.audit.events)


def test_sagemaker_contract_and_timeout_mapping(system):
    class RuntimeStub:
        def __init__(self):
            self.fail = False
            self.payload = {"model_version": "dtv-1.1", "state": "scored", "score": 0.7,
                            "confidence": 0.8, "reason": "classified"}
        def invoke_endpoint(self, **kwargs):
            self.seen = kwargs
            if self.fail:
                raise ReadTimeoutError(endpoint_url="https://example.invalid")
            return {"Body": io.BytesIO(json.dumps(self.payload).encode()), "ContentType": "application/json"}
    runtime = RuntimeStub()
    adapter = SageMakerClassifier(runtime, {"dtv-1.1": "hypothetical-specialist-v11"})
    assert adapter.classify(system.request).score == 0.7
    assert json.loads(runtime.seen["Body"])["model_version"] == "dtv-1.1"
    assert runtime.seen["ContentType"] == "application/json"
    runtime.payload["score"] = None
    with pytest.raises(ProviderFailure, match="provider_contract"):
        adapter.classify(system.request)
    runtime.fail = True
    with pytest.raises(ProviderFailure, match="provider_timeout"):
        adapter.classify(system.request)


def test_version_change_recomputes_and_response_mismatch_fails(system):
    s = system.service
    old = system.request.model_copy(update={"model_version": "dtv-1.0"})
    sid1 = s.submit(system.actor, [old], "version-one-key")[0]["id"]
    run_one(s)
    sid2 = s.submit(system.actor, [system.request], "version-two-key")[0]["id"]
    run_one(s)
    assert s.read(system.actor, sid1, old.purpose)["analysis"]["score"] == 0.72
    assert s.read(system.actor, sid2, old.purpose)["analysis"]["score"] == 0.68
    assert s.classifier.calls == 2
    class WrongVersion:
        simulated = False
        def classify(self, request):
            return ClassifierOutput(model_version="dtv-1.0", state="scored", score=0.8,
                                    confidence=0.8, reason="classified")
    s.classifier = WrongVersion()
    different = system.request.model_copy(update={"text": system.request.text + " Extra synthetic words."})
    sid3 = s.submit(system.actor, [different], "version-wrong-key")[0]["id"]
    run_one(s)
    assert s.read(system.actor, sid3, old.purpose)["error_code"] == "provider_contract"


@pytest.mark.parametrize("starting_state", ["queued", "failed", "scored"])
def test_deleted_work_cannot_be_recreated(system, starting_state):
    s, request = system.service, system.request
    if starting_state == "failed":
        s.classifier.failure = "provider_timeout"
    sid = s.submit(system.actor, [request], "delete-request")[0]["id"]
    job = Job("atlas", sid, 1)
    if starting_state != "queued":
        run_one(s)
    assert s.storage.get("atlas", sid).state == starting_state
    s.delete(system.actor, sid)
    calls = s.classifier.calls
    s.jobs.send(job)  # Simulate a late duplicate from an at-least-once provider.
    run_one(s)
    assert s.classifier.calls == calls
    assert ("atlas", sid) not in s.storage.records
    for operation in [lambda: s.retry(system.actor, sid, request.purpose),
                      lambda: s.submit(system.actor, [request], "delete-request")]:
        with pytest.raises(ProductError) as error:
            operation()
        assert error.value.status == 410


def test_deletion_erases_cache_features_and_fingerprint(system):
    s = system.service
    sid = s.submit(system.actor, [system.request], "erase-request")[0]["id"]
    run_one(s)
    held = s.storage.get("atlas", sid)
    assert held.features and s.storage.cache
    s.delete(system.actor, sid)
    assert held.request is None and held.output is None and not held.features
    assert held.judgment is None and held.cache_key == ""
    assert not s.storage.cache and not s.jobs.pending and not s.jobs.leased
    assert ("atlas", sid) in s.storage.tombstones
    assert all(fingerprint is None for fingerprint, ids in s.storage.idempotency.values())
    assert system.request.text not in repr(s.audit.events)


def test_sqs_reference_only_mapping(system):
    class QueueStub:
        def __init__(self):
            self.body = None
            self.deleted = []
        def send_message(self, **kwargs):
            self.sent = kwargs
            self.body = kwargs["MessageBody"]
            return {"MessageId": "synthetic-message"}
        def receive_message(self, **kwargs):
            self.received = kwargs
            return {"Messages": [{"Body": self.body, "ReceiptHandle": "synthetic-receipt"}]}
        def delete_message(self, **kwargs):
            self.deleted.append(kwargs)
            return {}
    stub = QueueStub()
    queue = SqsQueue(stub, "https://sqs.eu-west-1.amazonaws.com/000000000000/hypothetical-existing")
    job = Job("atlas", "00000000-0000-4000-8000-000000000001", 1)
    queue.send(job)
    assert json.loads(stub.body) == {"tenant": "atlas", "submission_id": job.submission_id, "attempt": 1}
    assert system.request.text not in stub.body
    receipt, received = queue.receive()
    assert received == job
    assert stub.received["VisibilityTimeout"] == 30
    queue.ack(receipt)
    assert stub.deleted[0]["ReceiptHandle"] == "synthetic-receipt"
    stub.body = '{"text":"sensitive poison body"}'
    assert queue.receive() is None
    assert len(stub.deleted) == 2


def test_idempotency_and_duplicate_delivery(system):
    s = system.service
    sid = s.submit(system.actor, [system.request], "same-request-key")[0]["id"]
    assert s.submit(system.actor, [system.request], "same-request-key")[0]["id"] == sid
    assert len(s.jobs.pending) == 1
    run_one(s)
    s.process(Job("atlas", sid, 1))
    assert s.classifier.calls == 1
    changed = system.request.model_copy(update={"text": system.request.text + " Another sentence."})
    with pytest.raises(ProductError, match="idempotency_conflict"):
        s.submit(system.actor, [changed], "same-request-key")

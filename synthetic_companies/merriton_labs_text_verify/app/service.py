from uuid import uuid4
from .auth import Directory, require_role
from .audit import Audit
from .cache import cache_key, request_fingerprint
from .domain import Principal, Submission, Job
from .errors import ProductError, safe_error
from .notices import Notices
from .onboarding import Onboarding
from .ports import Storage, Clock, Classifier, JobTransport
from .presentation import result_envelope
from .registry import Registry
from .schemas import SubmissionRequest, ClassifierOutput
from .validation import validate_use, validate_key, normalize_output


class VerifyService:
    def __init__(self, storage: Storage, classifier: Classifier, jobs: JobTransport,
                 clock: Clock, directory: Directory, onboarding: Onboarding,
                 registry: Registry, notices: Notices, audit: Audit):
        self.storage, self.classifier, self.jobs, self.clock = storage, classifier, jobs, clock
        self.directory, self.onboarding = directory, onboarding
        self.registry, self.notices, self.audit = registry, notices, audit

    def authorize(self, principal: Principal, *roles: str) -> None:
        # Re-check trusted membership so stale caller principals cannot bypass revocation.
        if self.directory.current(principal.subject) != principal:
            raise ProductError("forbidden", 403)
        require_role(principal, *roles)
        self.onboarding.require(principal)

    def submit(self, principal: Principal, items: list[SubmissionRequest], key: str,
               operation: str = "single") -> list[dict]:
        with self.storage.lock:
            self.authorize(principal, "editor", "admin")
            validate_key(key)
            if not 1 <= len(items) <= 10 or operation not in {"single", "batch"}:
                raise ProductError("invalid_input", 422)
            # Validate the entire batch before writing or sending any work.
            for request in items:
                validate_use(request, self.registry)
            scope = (principal.tenant, principal.subject, operation + ":" + key)
            fingerprint = request_fingerprint(items)
            prior = self.storage.idempotency.get(scope)
            if prior:
                if prior[0] is None:
                    raise ProductError("deleted", 410)
                if prior[0] != fingerprint:
                    raise ProductError("idempotency_conflict", 409)
                return [self.read(principal, sid, items[i].purpose) for i, sid in enumerate(prior[1])]
            records = []
            for request in items:
                record = Submission(str(uuid4()), principal.tenant, principal.subject,
                                    request.model_copy(deep=True), self.clock.now(),
                                    cache_key(principal.tenant, request), self.notices.active)
                self.storage.records[(principal.tenant, record.id)] = record
                records.append(record)
            self.storage.idempotency[scope] = (fingerprint, [r.id for r in records])
            for record in records:
                self.audit.emit(principal, "submitted", record.id, record.request.model_version)
                try:
                    self.jobs.send(Job(principal.tenant, record.id, record.attempt))
                except ProductError:
                    self.fail(record, principal, "queue_unavailable")
            return [self.read(principal, r.id, r.request.purpose) for r in records]

    def checked_record(self, principal: Principal, sid: str, purpose: str) -> Submission:
        self.authorize(principal, "editor", "admin")
        if purpose != "business_editorial_review":
            raise ProductError("purpose_rejected", 422)
        record = self.storage.get(principal.tenant, sid)
        validate_use(record.request, self.registry)
        return record

    def read(self, principal: Principal, sid: str, purpose: str) -> dict:
        with self.storage.lock:
            record = self.checked_record(principal, sid, purpose)
            model = self.registry.require(record.request.model_version, record.request.domain)
            return result_envelope(record, model, self.notices, self.classifier.simulated)

    def process(self, job: Job) -> None:
        # Lock spans inference and commit. Deletion waits, then erases a completed result;
        # deletion first means this worker cannot invoke or recreate anything.
        with self.storage.lock:
            key = (job.tenant, job.submission_id)
            if key in self.storage.tombstones or key not in self.storage.records:
                return
            record = self.storage.records[key]
            if record.state != "queued" or record.attempt != job.attempt:
                return
            principal = Principal(job.tenant, record.owner, "editor")
            try:
                current_principal = self.directory.current(record.owner)
                if current_principal.tenant != job.tenant:
                    raise ProductError("forbidden", 403)
                principal = current_principal
                self.authorize(principal, "editor", "admin")
                model = validate_use(record.request, self.registry)
                # No cache read until purpose, role, tenant, onboarding and release checks pass.
                output = self.storage.cache.get(record.cache_key)
                if output is None:
                    if record.request.language not in model.languages:
                        output = ClassifierOutput(model_version=model.version, state="abstained",
                                                  confidence=0.0, reason="unsupported_language")
                    else:
                        output = self.classifier.classify(record.request)
                output = normalize_output(output, record.request)
                self.storage.cache[record.cache_key] = output.model_copy(deep=True)
                record.output = output.model_copy(deep=True)
                record.features = {"characters": len(record.request.text)}
                record.analysis_limitations = model.limitations
                record.state = output.state
                self.audit.emit(principal, "analyzed", record.id, model.version)
            except ProductError as error:
                self.fail(record, principal, error.code)
            except Exception:
                # Unknown provider bugs are safe failures, never invented detector output.
                self.fail(record, principal, "internal_error")

    def fail(self, record: Submission, principal: Principal, code: str) -> None:
        record.state, record.output = "failed", None
        record.error_code = safe_error(ProductError(code))["code"]
        self.audit.emit(principal, "failed", record.id, record.request.model_version)

    def retry(self, principal: Principal, sid: str, purpose: str) -> dict:
        with self.storage.lock:
            record = self.checked_record(principal, sid, purpose)
            if record.state == "failed":
                if record.attempt >= 3:
                    raise ProductError("not_ready", 409)
                record.attempt += 1
                record.state, record.error_code = "queued", None
                try:
                    self.jobs.send(Job(principal.tenant, sid, record.attempt))
                except ProductError:
                    self.fail(record, principal, "queue_unavailable")
                self.audit.emit(principal, "retried", sid, record.request.model_version)
            return self.read(principal, sid, purpose)

    def judge(self, principal: Principal, sid: str, purpose: str, decision: str) -> dict:
        with self.storage.lock:
            self.authorize(principal, "editor")
            record = self.checked_record(principal, sid, purpose)
            if record.state not in {"scored", "abstained"} or decision not in {"retain_flag", "dismiss_flag"}:
                raise ProductError("not_ready", 409)
            record.judgment = {"decision": decision, "editor": principal.subject,
                               "at": self.clock.now().isoformat(), "kind": "human_editorial_judgment"}
            self.audit.emit(principal, "reviewed", sid, record.request.model_version)
            return self.read(principal, sid, purpose)

    def delete(self, principal: Principal, sid: str) -> dict:
        with self.storage.lock:
            self.authorize(principal, "editor", "admin")
            key = (principal.tenant, sid)
            if key not in self.storage.tombstones:
                self.storage.get(principal.tenant, sid)  # Tenant check, even for a withdrawn model.
                self.storage.purge(principal.tenant, sid)
                self.jobs.cancel(principal.tenant, sid)
                self.audit.emit(principal, "deleted", sid)
            return {"id": sid, "state": "deleted", "notice": self.notices.current()}

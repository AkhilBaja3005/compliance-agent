from contextlib import AbstractContextManager
from datetime import datetime
from typing import Protocol, Any
from .domain import Job, Submission
from .schemas import SubmissionRequest, ClassifierOutput


class Clock(Protocol):
    def now(self) -> datetime: ...


class Classifier(Protocol):
    simulated: bool
    def classify(self, request: SubmissionRequest) -> ClassifierOutput: ...


class JobTransport(Protocol):
    def send(self, job: Job) -> None: ...
    def receive(self) -> tuple[str, Job] | None: ...
    def ack(self, receipt: str) -> None: ...
    def cancel(self, tenant: str, submission_id: str) -> None: ...


class Storage(Protocol):
    """Single-process atomic scope. A durable implementation needs equivalent transactions."""
    lock: AbstractContextManager
    records: dict[tuple[str, str], Submission]
    tombstones: set[tuple[str, str]]
    idempotency: dict[tuple[str, str, str], tuple[str | None, list[str]]]
    cache: dict[str, ClassifierOutput]
    def get(self, tenant: str, submission_id: str) -> Submission: ...
    def purge(self, tenant: str, submission_id: str) -> None: ...

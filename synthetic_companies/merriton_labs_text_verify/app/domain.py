from dataclasses import dataclass, field
from datetime import datetime
from .schemas import SubmissionRequest, ClassifierOutput


@dataclass(frozen=True)
class Principal:
    tenant: str
    subject: str
    role: str


@dataclass(frozen=True)
class Job:
    tenant: str
    submission_id: str
    attempt: int


@dataclass
class Submission:
    id: str
    tenant: str
    owner: str
    request: SubmissionRequest | None
    created_at: datetime
    cache_key: str
    submitted_notice_version: str
    state: str = "queued"
    attempt: int = 1
    output: ClassifierOutput | None = None
    error_code: str | None = None
    features: dict = field(default_factory=dict)
    judgment: dict | None = None
    analysis_limitations: tuple[str, ...] = ()

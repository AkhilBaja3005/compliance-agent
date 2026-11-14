from dataclasses import dataclass
from .ports import Clock
from .domain import Principal


@dataclass(frozen=True)
class AuditEvent:
    at: str
    tenant: str
    actor: str
    action: str
    submission_id: str
    model_version: str | None


class Audit:
    """Fixed fields only; never accepts free-form messages, text, scores or exceptions."""

    def __init__(self, clock: Clock):
        self.clock = clock
        self.events: list[AuditEvent] = []

    def emit(self, principal: Principal, action: str, submission_id: str,
             model_version: str | None = None) -> None:
        assert action in {"submitted", "analyzed", "failed", "retried", "deleted", "reviewed"}
        self.events.append(AuditEvent(self.clock.now().isoformat(), principal.tenant,
                                     principal.subject, action, submission_id, model_version))

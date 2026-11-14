from collections import deque
from uuid import uuid4
from .domain import Job


class FakeQueue:
    """At-least-once transport; cancellation removes queued and leased local references."""
    def __init__(self):
        self.pending: deque[tuple[str, Job]] = deque()
        self.leased: dict[str, Job] = {}

    def send(self, job: Job) -> None:
        self.pending.append((str(uuid4()), job))

    def receive(self) -> tuple[str, Job] | None:
        if not self.pending:
            return None
        receipt, job = self.pending.popleft()
        self.leased[receipt] = job
        return receipt, job

    def ack(self, receipt: str) -> None:
        self.leased.pop(receipt, None)

    def cancel(self, tenant: str, submission_id: str) -> None:
        def keep(job):
            return (job.tenant, job.submission_id) != (tenant, submission_id)
        self.pending = deque((r, j) for r, j in self.pending if keep(j))
        self.leased = {r: j for r, j in self.leased.items() if keep(j)}

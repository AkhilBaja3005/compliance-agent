from threading import RLock
from .domain import Submission
from .errors import ProductError
from .schemas import ClassifierOutput


class MemoryStorage:
    def __init__(self):
        self.lock = RLock()
        self.records: dict[tuple[str, str], Submission] = {}
        self.tombstones: set[tuple[str, str]] = set()
        self.idempotency: dict[tuple[str, str, str], tuple[str | None, list[str]]] = {}
        self.cache: dict[str, ClassifierOutput] = {}

    def get(self, tenant: str, submission_id: str) -> Submission:
        key = (tenant, submission_id)
        if key in self.tombstones:
            raise ProductError("deleted", 410)
        if key not in self.records:
            raise ProductError("not_found", 404)
        return self.records[key]

    def purge(self, tenant: str, submission_id: str) -> None:
        key = (tenant, submission_id)
        self.tombstones.add(key)  # Written before any data is removed.
        record = self.records.pop(key, None)
        if record:
            self.cache.pop(record.cache_key, None)
            record.request = None  # Also erase any in-process reference held by a caller.
            record.features.clear()
            record.output = None
            record.judgment = None
            record.cache_key = ""
        for scope, (_, ids) in list(self.idempotency.items()):
            if scope[0] == tenant and submission_id in ids:
                self.idempotency[scope] = (None, ids)  # No retained input-derived fingerprint.

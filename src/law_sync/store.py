"""Thread-safe law store: atomic swap of the rule index plus a sync history."""
from __future__ import annotations

import hashlib
import json
import threading
from datetime import datetime, timezone

from src.schemas.regulatory import LawSyncResult, RegulatoryRule, RuleChange

from .seed_laws import SEED_RULES, SEED_VERSION_BASE


def _index_hash(rules: dict[str, RegulatoryRule]) -> str:
    payload = {k: v.sha256_hash for k, v in sorted(rules.items())}
    return hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()


class LawStore:
    def __init__(self):
        self._lock = threading.RLock()
        self._rules: dict[str, RegulatoryRule] = {r.rule_id: r for r in SEED_RULES}
        self._version_counter = 1
        self.version = self._make_version()
        self.last_synced_at: datetime | None = None
        self.history: list[LawSyncResult] = []
        self._listeners: list = []

    def _make_version(self) -> str:
        return f"{SEED_VERSION_BASE}.{self._version_counter}+{_index_hash(self._rules)[:8]}"

    # --- reads
    def snapshot(self) -> dict[str, RegulatoryRule]:
        with self._lock:
            return dict(self._rules)

    def get(self, rule_id: str) -> RegulatoryRule | None:
        with self._lock:
            return self._rules.get(rule_id)

    def has_rule(self, rule_id: str) -> bool:
        return self.get(rule_id) is not None

    def add_listener(self, fn) -> None:
        self._listeners.append(fn)

    # --- atomic apply
    def apply(self, new_rules: dict[str, RegulatoryRule], source: str) -> LawSyncResult:
        with self._lock:
            old = self._rules
            changes: list[RuleChange] = []
            for rid, r in new_rules.items():
                if rid not in old:
                    changes.append(RuleChange(rule_id=rid, change="ADDED", new_hash=r.sha256_hash))
                elif old[rid].sha256_hash != r.sha256_hash:
                    changes.append(RuleChange(rule_id=rid, change="MODIFIED", old_hash=old[rid].sha256_hash, new_hash=r.sha256_hash))
            for rid, r in old.items():
                if rid not in new_rules:
                    changes.append(RuleChange(rule_id=rid, change="REMOVED", old_hash=r.sha256_hash))
            prev = self.version
            now = datetime.now(timezone.utc)
            log = [f"{c.change} {c.rule_id}" for c in changes] or ["no changes detected (SHA-256 identical)"]
            if not changes:
                # content identical: still adopt provenance metadata (e.g. fresh Linkup citations) without a version bump
                self._rules = dict(new_rules)
            if changes:
                self._rules = dict(new_rules)  # atomic pointer swap
                self._version_counter += 1
                self.version = self._make_version()
                for fn in self._listeners:
                    try:
                        fn(self)
                    except Exception as exc:  # re-index failure must not corrupt the store
                        log.append(f"listener error: {exc}")
            self.last_synced_at = now
            result = LawSyncResult(changed=bool(changes), previous_version=prev, new_version=self.version,
                                   synced_at=now, changes=changes, source=source, log=log)
            self.history.append(result)
            self.history = self.history[-50:]
            return result


_STORE: LawStore | None = None
_STORE_LOCK = threading.Lock()


def get_store() -> LawStore:
    global _STORE
    with _STORE_LOCK:
        if _STORE is None:
            _STORE = LawStore()
        return _STORE


def reset_store() -> LawStore:
    """Reset to seed state (used by tests)."""
    global _STORE
    with _STORE_LOCK:
        _STORE = LawStore()
        return _STORE

"""Thread-safe law store: atomic swap of the rule index plus a sync history."""
from __future__ import annotations

import hashlib
import json
import os
import threading
import uuid
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
        self.pending: dict[str, dict] = {}  # staged updates awaiting human approval (GRAPHITE_RULE_REVIEW_REQUIRED=true)

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

    # --- review gate: with GRAPHITE_RULE_REVIEW_REQUIRED=true, changed rule content is staged, not applied, until an admin approves it
    @staticmethod
    def review_required() -> bool:
        return os.getenv("GRAPHITE_RULE_REVIEW_REQUIRED", "").lower() == "true"

    def _diff(self, new_rules: dict[str, RegulatoryRule]) -> list[RuleChange]:
        old, changes = self._rules, []
        for rid, r in new_rules.items():
            if rid not in old:
                changes.append(RuleChange(rule_id=rid, change="ADDED", new_hash=r.sha256_hash))
            elif old[rid].sha256_hash != r.sha256_hash:
                changes.append(RuleChange(rule_id=rid, change="MODIFIED", old_hash=old[rid].sha256_hash, new_hash=r.sha256_hash))
        changes += [RuleChange(rule_id=rid, change="REMOVED", old_hash=r.sha256_hash) for rid, r in old.items() if rid not in new_rules]
        return changes

    def approve_pending(self, pending_id: str, reviewer: str) -> LawSyncResult:
        with self._lock:
            p = self.pending.pop(pending_id, None)
            if p is None:
                raise KeyError(pending_id)
            res = self.apply(p["rules"], f"approved:{pending_id} by {reviewer} (from {p['source']})", _approved=True)
            return res

    def reject_pending(self, pending_id: str) -> bool:
        with self._lock:
            return self.pending.pop(pending_id, None) is not None

    # --- atomic apply
    def apply(self, new_rules: dict[str, RegulatoryRule], source: str, _approved: bool = False) -> LawSyncResult:
        with self._lock:
            if self.review_required() and not _approved:
                staged = self._diff(new_rules)
                if staged:
                    pid = uuid.uuid4().hex[:10]
                    self.pending[pid] = {"rules": dict(new_rules), "changes": staged, "source": source, "created_at": datetime.now(timezone.utc)}
                    res = LawSyncResult(changed=False, previous_version=self.version, new_version=self.version, synced_at=datetime.now(timezone.utc),
                                        changes=staged, source=source, log=[f"STAGED {pid}: {len(staged)} change(s) await human approval; rule library unchanged"] + [f"{c.change} {c.rule_id}" for c in staged])
                    self.history.append(res)
                    return res
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

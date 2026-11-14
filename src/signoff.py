"""Human sign-off log: append-only, hash-chained records of who decided what on a report or finding, and when.

Findings are recommendations until a named human signs them off. Each record links to the previous record's hash, so edits or
deletions in the stored log are detectable with `verify()`. The reviewer identity is the authenticated key id plus a free-text name.
"""
from __future__ import annotations

import hashlib
import json
import threading
from datetime import datetime, timezone
from pathlib import Path

DECISIONS = {"approve", "reject", "needs_info"}


class SignoffLog:
    def __init__(self, data_dir: Path | None):
        self._file = (data_dir / "signoffs.jsonl") if data_dir else None
        self._records: list[dict] = []
        self._lock = threading.Lock()
        if self._file and self._file.is_file():
            self._records = [json.loads(l) for l in self._file.read_text().splitlines() if l.strip()]

    @staticmethod
    def _hash(rec: dict) -> str:
        body = {k: v for k, v in rec.items() if k != "hash"}
        return hashlib.sha256(json.dumps(body, sort_keys=True).encode()).hexdigest()

    def add(self, report_id: str, tenant: str, finding_id: str | None, decision: str, reviewer_key_id: str, reviewer_name: str, note: str = "") -> dict:
        if decision not in DECISIONS:
            raise ValueError(f"decision must be one of {sorted(DECISIONS)}")
        with self._lock:
            rec = {"seq": len(self._records) + 1, "report_id": report_id, "tenant": tenant, "finding_id": finding_id, "decision": decision,
                   "reviewer_key_id": reviewer_key_id, "reviewer_name": reviewer_name[:120], "note": note[:2000],
                   "at": datetime.now(timezone.utc).isoformat(), "prev_hash": self._records[-1]["hash"] if self._records else "0" * 64}
            rec["hash"] = self._hash(rec)
            self._records.append(rec)
            if self._file:
                self._file.parent.mkdir(parents=True, exist_ok=True)
                with self._file.open("a") as fh:
                    fh.write(json.dumps(rec) + "\n")
            return rec

    def for_report(self, report_id: str) -> list[dict]:
        return [r for r in self._records if r["report_id"] == report_id]

    def verify(self) -> tuple[bool, int | None]:
        prev = "0" * 64
        for r in self._records:
            if r["prev_hash"] != prev or r["hash"] != self._hash(r):
                return False, r["seq"]
            prev = r["hash"]
        return True, None

    def status(self, report_id: str, finding_ids: list[str]) -> dict:
        """Latest decision per finding plus a report-level summary."""
        latest: dict[str | None, dict] = {}
        for r in self.for_report(report_id):
            latest[r["finding_id"]] = r
        signed = {f: latest[f]["decision"] for f in finding_ids if f in latest}
        return {"report_decision": (latest.get(None) or {}).get("decision"), "findings": signed,
                "unreviewed": [f for f in finding_ids if f not in latest], "records": len(self.for_report(report_id))}

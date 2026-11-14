"""Asynchronous audit jobs with idempotency, status, cancellation, timeout marking and optional on-disk persistence.

Honest limits: a running Python thread cannot be killed, so `cancel` on a running job and a timeout both mark the job and discard
its result when the thread finishes. A process restart does not resume a running audit: unfinished jobs are marked `interrupted`
on startup and can be resubmitted (the idempotency key then returns the same job record).
"""
from __future__ import annotations

import json
import os
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Callable

TERMINAL = {"succeeded", "failed", "cancelled", "timed_out", "interrupted"}


@dataclass
class Job:
    job_id: str
    tenant: str
    owner: str  # key id of the submitter
    params: dict
    status: str = "queued"
    created_at: float = field(default_factory=time.time)
    started_at: float | None = None
    finished_at: float | None = None
    report_id: str | None = None
    error: str | None = None
    idempotency_key: str | None = None
    cancel_requested: bool = False

    def public(self) -> dict:
        d = asdict(self)
        d.pop("params", None)
        return d


class ReportStore:
    """Finished reports by id (memory; mirrored to AEGIS_DATA_DIR/reports when set)."""

    def __init__(self, data_dir: Path | None):
        self._mem: dict[str, tuple[str, dict]] = {}
        self._dir = (data_dir / "reports") if data_dir else None
        if self._dir:
            self._dir.mkdir(parents=True, exist_ok=True)
            for p in self._dir.glob("*.json"):
                try:
                    d = json.loads(p.read_text())
                    self._mem[d["report"]["report_id"]] = (d["tenant"], d["report"])
                except (ValueError, KeyError):
                    continue

    def put(self, tenant: str, report: dict) -> None:
        self._mem[report["report_id"]] = (tenant, report)
        if self._dir:
            tmp = self._dir / f".{report['report_id']}.tmp"
            tmp.write_text(json.dumps({"tenant": tenant, "report": report}, default=str))
            tmp.replace(self._dir / f"{report['report_id']}.json")

    def get(self, report_id: str) -> tuple[str, dict] | None:
        return self._mem.get(report_id)


class JobManager:
    def __init__(self, run_fn: Callable[[dict], dict], reports: ReportStore, workers: int | None = None, timeout_s: float | None = None, data_dir: Path | None = None):
        self.run_fn, self.reports = run_fn, reports
        self.timeout_s = timeout_s if timeout_s is not None else float(os.getenv("AEGIS_JOB_TIMEOUT_S", "900"))
        self.pool = ThreadPoolExecutor(max_workers=workers or int(os.getenv("AEGIS_WORKERS", "2")), thread_name_prefix="aegis-job")
        self.jobs: dict[str, Job] = {}
        self.idem: dict[tuple[str, str], str] = {}
        self._lock = threading.RLock()
        self._file = (data_dir / "jobs.json") if data_dir else None
        self._load()

    # -------------------------------------------------- persistence
    def _load(self) -> None:
        if not self._file or not self._file.is_file():
            return
        try:
            for d in json.loads(self._file.read_text()):
                j = Job(**d)
                if j.status not in TERMINAL:
                    j.status, j.error, j.finished_at = "interrupted", "process restarted before completion", time.time()
                self.jobs[j.job_id] = j
                if j.idempotency_key:
                    self.idem[(j.owner, j.idempotency_key)] = j.job_id
        except (ValueError, TypeError):
            pass

    def _save(self) -> None:
        if not self._file:
            return
        self._file.parent.mkdir(parents=True, exist_ok=True)
        tmp = self._file.with_suffix(".tmp")
        tmp.write_text(json.dumps([asdict(j) for j in self.jobs.values()], default=str))
        tmp.replace(self._file)

    # -------------------------------------------------- API
    def submit(self, tenant: str, params: dict, owner: str, idempotency_key: str | None = None) -> tuple[Job, bool]:
        with self._lock:
            if idempotency_key and (owner, idempotency_key) in self.idem:
                return self.jobs[self.idem[(owner, idempotency_key)]], False
            job = Job(uuid.uuid4().hex[:16], tenant, owner, params, idempotency_key=idempotency_key)
            self.jobs[job.job_id] = job
            if idempotency_key:
                self.idem[(owner, idempotency_key)] = job.job_id
            self._save()
        self.pool.submit(self._run, job.job_id)
        return job, True

    def get(self, job_id: str) -> Job | None:
        return self.jobs.get(job_id)

    def cancel(self, job_id: str) -> Job | None:
        with self._lock:
            j = self.jobs.get(job_id)
            if j is None or j.status in TERMINAL:
                return j
            j.cancel_requested = True
            if j.status == "queued":
                j.status, j.finished_at = "cancelled", time.time()
            self._save()
            return j

    def _run(self, job_id: str) -> None:
        j = self.jobs[job_id]
        with self._lock:
            if j.status != "queued":
                return
            j.status, j.started_at = "running", time.time()
            self._save()
        timer = threading.Timer(self.timeout_s, self._timeout, args=(job_id,))
        timer.daemon = True
        timer.start()
        try:
            report = self.run_fn(j.params)
            with self._lock:
                if j.status != "running":  # timed out while running
                    return
                if j.cancel_requested:
                    j.status = "cancelled"
                else:
                    self.reports.put(j.tenant, report)
                    j.report_id, j.status = report["report_id"], "succeeded"
        except Exception as exc:
            with self._lock:
                if j.status == "running":
                    j.status, j.error = "failed", f"{type(exc).__name__}: {str(exc)[:300]}"
        finally:
            timer.cancel()
            with self._lock:
                j.finished_at = j.finished_at or time.time()
                self._save()

    def _timeout(self, job_id: str) -> None:
        with self._lock:
            j = self.jobs[job_id]
            if j.status == "running":
                j.status, j.error, j.finished_at = "timed_out", f"exceeded {self.timeout_s:g}s", time.time()
                self._save()

    def wait(self, job_id: str, timeout: float = 30.0) -> Job:
        end = time.time() + timeout
        while time.time() < end:
            j = self.jobs[job_id]
            if j.status in TERMINAL:
                return j
            time.sleep(0.02)
        return self.jobs[job_id]

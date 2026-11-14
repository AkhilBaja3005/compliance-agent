"""Durable dashboard repository. Reports are shared by API, CLI and scanner runs.

SQLite uses short connections/transactions so separate scanner processes can publish
to the same database. MongoDB uses separate collections in the existing Atlas DB.
"""
from __future__ import annotations

import logging
import os
import sqlite3
import threading
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Protocol

from src.dashboard.models import Job, ReportSummary, SettingsRecord, Sources, StorageStatus
from src.schemas.findings import TriagedAuditReport

log = logging.getLogger(__name__)


def now() -> datetime:
    return datetime.now(timezone.utc)


def timestamp(value: datetime) -> str:
    return (value if value.tzinfo else value.replace(tzinfo=timezone.utc)).astimezone(timezone.utc).isoformat()


class DashboardRepository(Protocol):
    mode: str
    warning: str | None

    def save_report(self, report: TriagedAuditReport) -> None: ...
    def get_report(self, company_id: str, report_id: str) -> TriagedAuditReport | None: ...
    def recent_reports(self, company_id: str, limit: int = 30) -> list[ReportSummary]: ...
    def get_settings(self, company_id: str) -> SettingsRecord: ...
    def save_settings(self, settings: SettingsRecord) -> None: ...
    def all_settings(self) -> list[SettingsRecord]: ...
    def enqueue(self, company_id: str, sources: Sources, trigger: str) -> tuple[Job, bool]: ...
    def get_job(self, company_id: str, job_id: str) -> Job | None: ...
    def latest_job(self, company_id: str) -> Job | None: ...
    def save_job(self, job: Job) -> None: ...
    def fail_interrupted(self) -> None: ...


def new_job(company_id: str, sources: Sources, trigger: str) -> Job:
    return Job(job_id=uuid.uuid4().hex, company_id=company_id, trigger=trigger, created_at=now(), sources=sources)


class SQLiteDashboardRepository:
    mode = "sqlite"

    def __init__(self, path: str | Path, warning: str | None = None):
        self.path, self.warning = str(path), warning
        Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        with self.connection() as db:
            db.execute("PRAGMA journal_mode=WAL")
            db.executescript("""
                CREATE TABLE IF NOT EXISTS dashboard_reports (
                    company_id TEXT NOT NULL, report_id TEXT NOT NULL, assessed_at TEXT NOT NULL,
                    summary TEXT NOT NULL, payload TEXT NOT NULL, PRIMARY KEY(company_id, report_id));
                CREATE INDEX IF NOT EXISTS dashboard_report_time
                    ON dashboard_reports(company_id, assessed_at DESC, report_id DESC);
                CREATE TABLE IF NOT EXISTS dashboard_settings (company_id TEXT PRIMARY KEY, payload TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS dashboard_jobs (
                    job_id TEXT PRIMARY KEY, company_id TEXT NOT NULL, state TEXT NOT NULL,
                    created_at TEXT NOT NULL, payload TEXT NOT NULL);
                CREATE UNIQUE INDEX IF NOT EXISTS dashboard_active_company
                    ON dashboard_jobs(company_id) WHERE state IN ('queued', 'running');
                CREATE INDEX IF NOT EXISTS dashboard_job_time ON dashboard_jobs(company_id, created_at DESC);
            """)

    @contextmanager
    def connection(self):
        db = sqlite3.connect(self.path, timeout=15)
        try:
            with db:
                yield db
        finally:
            db.close()

    def save_report(self, report):
        summary = ReportSummary.from_report(report)
        with self.connection() as db:
            db.execute("INSERT OR IGNORE INTO dashboard_reports VALUES (?, ?, ?, ?, ?)",
                       (report.tenant_id, report.report_id, timestamp(summary.assessed_at),
                        summary.model_dump_json(), report.model_dump_json()))

    def get_report(self, company_id, report_id):
        with self.connection() as db:
            row = db.execute("SELECT payload FROM dashboard_reports WHERE company_id=? AND report_id=?",
                             (company_id, report_id)).fetchone()
        return TriagedAuditReport.model_validate_json(row[0]) if row else None

    def recent_reports(self, company_id, limit=30):
        with self.connection() as db:
            rows = db.execute("SELECT summary FROM dashboard_reports WHERE company_id=? "
                              "ORDER BY assessed_at DESC, report_id DESC LIMIT ?", (company_id, limit)).fetchall()
        return [ReportSummary.model_validate_json(row[0]) for row in rows]

    def get_settings(self, company_id):
        with self.connection() as db:
            row = db.execute("SELECT payload FROM dashboard_settings WHERE company_id=?", (company_id,)).fetchone()
        return SettingsRecord.model_validate_json(row[0]) if row else SettingsRecord(company_id=company_id)

    def save_settings(self, settings):
        with self.connection() as db:
            db.execute("INSERT INTO dashboard_settings VALUES (?, ?) ON CONFLICT(company_id) "
                       "DO UPDATE SET payload=excluded.payload", (settings.company_id, settings.model_dump_json()))

    def all_settings(self):
        with self.connection() as db:
            rows = db.execute("SELECT payload FROM dashboard_settings").fetchall()
        return [SettingsRecord.model_validate_json(row[0]) for row in rows]

    def enqueue(self, company_id, sources, trigger):
        job = new_job(company_id, sources, trigger)
        with self.connection() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("SELECT payload FROM dashboard_jobs WHERE company_id=? AND state IN ('queued', 'running')",
                             (company_id,)).fetchone()
            if row:
                return Job.model_validate_json(row[0]), False
            db.execute("INSERT INTO dashboard_jobs VALUES (?, ?, ?, ?, ?)",
                       (job.job_id, company_id, job.state, timestamp(job.created_at), job.model_dump_json()))
        return job, True

    def get_job(self, company_id, job_id):
        with self.connection() as db:
            row = db.execute("SELECT payload FROM dashboard_jobs WHERE company_id=? AND job_id=?",
                             (company_id, job_id)).fetchone()
        return Job.model_validate_json(row[0]) if row else None

    def latest_job(self, company_id):
        with self.connection() as db:
            row = db.execute("SELECT payload FROM dashboard_jobs WHERE company_id=? ORDER BY created_at DESC, job_id DESC LIMIT 1",
                             (company_id,)).fetchone()
        return Job.model_validate_json(row[0]) if row else None

    def save_job(self, job):
        with self.connection() as db:
            db.execute("UPDATE dashboard_jobs SET state=?, payload=? WHERE company_id=? AND job_id=?",
                       (job.state, job.model_dump_json(), job.company_id, job.job_id))

    def fail_interrupted(self):
        with self.connection() as db:
            db.execute("BEGIN IMMEDIATE")
            rows = db.execute("SELECT payload FROM dashboard_jobs WHERE state IN ('queued', 'running')").fetchall()
            for row in rows:
                job = interrupted(Job.model_validate_json(row[0]))
                db.execute("UPDATE dashboard_jobs SET state=?, payload=? WHERE job_id=?",
                           (job.state, job.model_dump_json(), job.job_id))


def interrupted(job: Job) -> Job:
    return job.model_copy(update={"state": "failed", "finished_at": now(),
                                  "error": "Audit interrupted by application restart; run it again."})


class MongoDashboardRepository:
    mode = "mongodb"
    warning = None

    def __init__(self, db):
        self.reports = db["dashboard_reports"]
        self.settings = db["dashboard_settings"]
        self.jobs = db["dashboard_jobs"]
        self.reports.create_index([("company_id", 1), ("report_id", 1)], unique=True)
        self.reports.create_index([("company_id", 1), ("assessed_at", -1), ("report_id", -1)])
        self.settings.create_index("company_id", unique=True)
        self.jobs.create_index("job_id", unique=True)
        self.jobs.create_index("company_id", unique=True, partialFilterExpression={"active": True})
        self.jobs.create_index([("company_id", 1), ("created_at", -1)])

    def save_report(self, report):
        summary = ReportSummary.from_report(report)
        key = {"company_id": report.tenant_id, "report_id": report.report_id}
        self.reports.update_one(key, {"$setOnInsert": {**key, "assessed_at": timestamp(summary.assessed_at),
                                "summary": summary.model_dump(mode="json"), "payload": report.model_dump(mode="json")}}, upsert=True)

    def get_report(self, company_id, report_id):
        row = self.reports.find_one({"company_id": company_id, "report_id": report_id})
        return TriagedAuditReport.model_validate(row["payload"]) if row else None

    def recent_reports(self, company_id, limit=30):
        return [ReportSummary.model_validate(row["summary"]) for row in self.reports.find({"company_id": company_id})
                .sort([("assessed_at", -1), ("report_id", -1)]).limit(limit)]

    def get_settings(self, company_id):
        row = self.settings.find_one({"company_id": company_id})
        return SettingsRecord.model_validate(row["payload"]) if row else SettingsRecord(company_id=company_id)

    def save_settings(self, settings):
        self.settings.update_one({"company_id": settings.company_id},
                                 {"$set": {"payload": settings.model_dump(mode="json")}}, upsert=True)

    def all_settings(self):
        return [SettingsRecord.model_validate(row["payload"]) for row in self.settings.find({})]

    def enqueue(self, company_id, sources, trigger):
        from pymongo.errors import DuplicateKeyError

        job = new_job(company_id, sources, trigger)
        # A unique partial index makes deduplication atomic across request threads.
        try:
            self.jobs.insert_one(self.job_document(job))
            return job, True
        except DuplicateKeyError:
            row = self.jobs.find_one({"company_id": company_id, "active": True})
            if row is None:  # active job completed between the insert and lookup
                return self.enqueue(company_id, sources, trigger)
            return Job.model_validate(row["payload"]), False

    @staticmethod
    def job_document(job):
        return {"job_id": job.job_id, "company_id": job.company_id, "created_at": timestamp(job.created_at),
                "active": job.state in ("queued", "running"), "payload": job.model_dump(mode="json")}

    def get_job(self, company_id, job_id):
        row = self.jobs.find_one({"company_id": company_id, "job_id": job_id})
        return Job.model_validate(row["payload"]) if row else None

    def latest_job(self, company_id):
        row = self.jobs.find_one({"company_id": company_id}, sort=[("created_at", -1), ("job_id", -1)])
        return Job.model_validate(row["payload"]) if row else None

    def save_job(self, job):
        self.jobs.replace_one({"company_id": job.company_id, "job_id": job.job_id}, self.job_document(job))

    def fail_interrupted(self):
        for row in self.jobs.find({"active": True}):
            self.save_job(interrupted(Job.model_validate(row["payload"])))


_repositories: dict[tuple, DashboardRepository] = {}
_errors: dict[str, str] = {}
_lock = threading.RLock()


def get_dashboard_repository() -> DashboardRepository:
    path = os.getenv("GRAPHITE_DASHBOARD_DB") or str(Path(__file__).resolve().parents[2] / ".aegis" / "dashboard.sqlite3")
    key = (path, os.getenv("MONGODB_URI"), os.getenv("MONGODB_DATABASE"), os.getenv("MONGODB_DB_NAME"))
    with _lock:
        if key not in _repositories:
            from src.storage import get_compliance_store

            store = get_compliance_store()
            if store.is_atlas:
                try:
                    repository = MongoDashboardRepository(store.db)
                except Exception as exc:
                    log.warning("MongoDB dashboard initialization failed: %s; using SQLite", type(exc).__name__)
                    repository = SQLiteDashboardRepository(path, "MongoDB dashboard storage unavailable; using SQLite.")
            else:
                repository = SQLiteDashboardRepository(path, "MongoDB unavailable; using SQLite." if store.error else None)
            # Once selected, runtime failures are surfaced; never silently split writes between backends.
            _repositories[key] = repository
        return _repositories[key]


def storage_status(repository: DashboardRepository, company_id: str) -> StorageStatus:
    with _lock:
        return StorageStatus(mode=repository.mode, warning=repository.warning, persistence_error=_errors.get(company_id))


def publish_completed_report(report: TriagedAuditReport) -> None:
    """Best effort hook: failures remain visible in telemetry, logs and dashboard snapshots."""
    try:
        repository = get_dashboard_repository()
        report.stack_telemetry["dashboard_persistence"] = {"status": "saved", "mode": repository.mode}
        repository.save_report(report)
        with _lock:
            _errors.pop(report.tenant_id, None)
    except Exception as exc:
        # Do not expose connection strings, tokens or connector exception messages to browsers.
        error = f"Completed report could not be saved ({type(exc).__name__}); check server storage and logs."
        report.stack_telemetry["dashboard_persistence"] = {"status": "failed", "error": error}
        with _lock:
            _errors[report.tenant_id] = error
        log.error("Dashboard persistence failed for tenant %s: %s", report.tenant_id, type(exc).__name__)

"""One audit worker and interval schedules owned by the FastAPI lifespan."""
from __future__ import annotations

import logging
import queue
import threading
from datetime import timedelta, timezone
from pathlib import Path
from typing import Callable

from apscheduler.schedulers.background import BackgroundScheduler

from src.dashboard.models import Job, Settings, SettingsRecord, Snapshot
from src.storage.dashboard import DashboardRepository, now, storage_status

log = logging.getLogger(__name__)
INTERVALS = {"hourly": timedelta(hours=1), "daily": timedelta(days=1), "weekly": timedelta(weeks=1)}


class DashboardService:
    def __init__(self, repository: DashboardRepository, company_ids: Callable[[], list[str]],
                 company_root: Callable[[], Path], runner=None):
        self.repository, self.company_ids, self.company_root = repository, company_ids, company_root
        self.runner = runner
        self.scheduler = BackgroundScheduler(timezone=timezone.utc)
        self._lock = threading.RLock()
        self._queue: queue.Queue[Job | None] = queue.Queue()
        self._stopping = threading.Event()
        self._thread = threading.Thread(target=self._work, name="dashboard-audit-worker", daemon=True)
        self.last_error: str | None = None

    def start(self):
        self.repository.fail_interrupted()
        self.scheduler.start(paused=True)
        try:
            known = set(self.company_ids())
            for record in self.repository.all_settings():
                if record.company_id in known and record.schedule.enabled:
                    record.next_run_at = self._future_run(record)
                    self.repository.save_settings(record)
                    self._install_schedule(record)
            self._thread.start()
            self.scheduler.resume()
        except Exception:
            self.scheduler.shutdown(wait=False)
            raise

    def stop(self):
        self._stopping.set()
        self.scheduler.shutdown(wait=True)
        self._queue.put(None)
        # Finish an audit already in progress. Queued jobs are marked failed on restart.
        if self._thread.is_alive():
            self._thread.join()

    @staticmethod
    def _future_run(record):
        interval, current = INTERVALS[record.schedule.frequency], now()
        candidate = record.next_run_at or current + interval
        if candidate.tzinfo is None:
            candidate = candidate.replace(tzinfo=timezone.utc)
        if candidate <= current:
            candidate += (int((current - candidate) // interval) + 1) * interval
        return candidate

    def save_settings(self, company_id: str, settings: Settings) -> SettingsRecord:
        with self._lock:
            previous = self.repository.get_settings(company_id)
            record = SettingsRecord(company_id=company_id, **settings.model_dump())
            if record.schedule.enabled:
                if previous.schedule == record.schedule:
                    record.next_run_at = previous.next_run_at
                record.next_run_at = self._future_run(record)
            self.repository.save_settings(record)
            self._install_schedule(record)
            return record

    def _install_schedule(self, record):
        job_id = f"audit:{record.company_id}"
        if self.scheduler.get_job(job_id):
            self.scheduler.remove_job(job_id)
        if record.schedule.enabled:
            self.scheduler.add_job(
                self._scheduled, "interval", seconds=INTERVALS[record.schedule.frequency].total_seconds(),
                next_run_time=record.next_run_at, args=[record.company_id], id=job_id,
                coalesce=True, misfire_grace_time=1, max_instances=1, replace_existing=True,
            )

    def _scheduled(self, company_id):
        try:
            with self._lock:
                record = self.repository.get_settings(company_id)
                if not record.schedule.enabled or self._stopping.is_set():
                    return
                record.next_run_at = self._future_run(record)
                self.repository.save_settings(record)
                self.enqueue(company_id, "scheduled")
        except Exception as exc:
            self.last_error = f"Scheduled audit could not be queued ({type(exc).__name__}); check server storage."
            log.error("Scheduled dashboard audit failed for %s: %s", company_id, type(exc).__name__)

    def enqueue(self, company_id: str, trigger="manual") -> Job:
        with self._lock:
            if self._stopping.is_set():
                raise RuntimeError("Dashboard is shutting down")
            settings = self.repository.get_settings(company_id)
            job, created = self.repository.enqueue(company_id, settings.sources, trigger)
            if created:
                self._queue.put(job)
            return job

    def _work(self):
        while not self._stopping.is_set():
            job = self._queue.get()
            if job is None or self._stopping.is_set():
                return
            try:
                job.state, job.started_at = "running", now()
                self.repository.save_job(job)
                from src.agents import run_audit

                runner = self.runner or run_audit
                root = self.company_root
                if callable(root):
                    try:
                        company_dir = root(job.company_id)
                    except TypeError:
                        company_dir = root() / job.company_id
                elif isinstance(root, Path):
                    company_dir = root / job.company_id
                else:
                    company_dir = Path(str(root)) / job.company_id

                report = runner(
                    company_dir, job.company_id, known_tenants=set(self.company_ids()),
                    github_source=job.sources.github_url,
                    confluence_source=job.sources.confluence_path or ("cloud" if job.sources.confluence_space_key else None),
                    space_key=job.sources.confluence_space_key,
                )
                if report.tenant_id != job.company_id:
                    raise ValueError("Audit returned a different tenant")
                if self.repository.get_report(job.company_id, report.report_id) is None:
                    raise RuntimeError("Completed report was not persisted")
                job.state, job.report_id = "succeeded", report.report_id
            except Exception as exc:
                job.state = "failed"
                job.error = f"Audit failed ({type(exc).__name__}). Check source settings and server logs, then retry."
                log.error("Dashboard audit %s failed: %s", job.job_id, type(exc).__name__)
            finally:
                job.finished_at = now()
                try:
                    self.repository.save_job(job)
                except Exception as exc:
                    self.last_error = "Audit activity could not be saved; check server storage and restart the application."
                    log.error("Dashboard job state save failed: %s", type(exc).__name__)

    def snapshot(self, company_id: str) -> Snapshot:
        with self._lock:
            recent = self.repository.recent_reports(company_id)
            record = self.repository.get_settings(company_id)
            scheduled = self.scheduler.get_job(f"audit:{company_id}")
            status = storage_status(self.repository, company_id)
            status.persistence_error = status.persistence_error or self.last_error
            return Snapshot(
                company_id=company_id, latest_report=recent[0] if recent else None, trends=list(reversed(recent)),
                latest_job=self.repository.latest_job(company_id), settings=Settings(**record.model_dump(include={"sources", "schedule"})),
                next_scheduled_run=scheduled.next_run_time if scheduled else None, storage=status, refreshed_at=now(),
            )

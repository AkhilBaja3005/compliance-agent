"""24-hour background sync scheduler (APScheduler)."""
from __future__ import annotations

from datetime import datetime

from apscheduler.schedulers.background import BackgroundScheduler

import logging

from .store import get_store

log = logging.getLogger("aegis.sync")

JOB_ID = "daily-law-sync"
_scheduler: BackgroundScheduler | None = None


def scheduled_full_sync() -> None:
    """The scheduled job: statutory rules + configured folders/urls. Failures are logged, never raised (the scheduler keeps running)."""
    try:
        from .ingest import run_full_sync

        rep = run_full_sync()
        log.info("scheduled sync finished", extra={"event": "sync_done"})
        for r in rep.errors:
            log.warning("scheduled sync source failed: %s: %s", r.source, r.detail)
    except Exception:
        log.exception("scheduled sync crashed")


def start_scheduler(interval_hours: float = 24, run_immediately: bool = False) -> BackgroundScheduler:
    global _scheduler
    if _scheduler is not None and _scheduler.running:
        return _scheduler
    _scheduler = BackgroundScheduler(daemon=True)
    kwargs = {"next_run_time": datetime.now().astimezone()} if run_immediately else {}  # None would pause the job
    _scheduler.add_job(scheduled_full_sync, "interval", hours=interval_hours, id=JOB_ID, replace_existing=True, **kwargs)
    _scheduler.start()
    return _scheduler


def stop_scheduler() -> None:
    global _scheduler
    if _scheduler is not None and _scheduler.running:
        _scheduler.shutdown(wait=False)
    _scheduler = None


def scheduler_running() -> bool:
    return _scheduler is not None and _scheduler.running


def next_sync_at() -> datetime | None:
    if not scheduler_running():
        return None
    job = _scheduler.get_job(JOB_ID)
    return getattr(job, "next_run_time", None) if job else None


def law_status():
    from src.schemas.regulatory import LawIndexStatus

    st = get_store()
    return LawIndexStatus(
        law_index_version=st.version, last_synced_at=st.last_synced_at, rule_count=len(st.snapshot()),
        scheduler_running=scheduler_running(), next_sync_at=next_sync_at(), history=st.history[-10:],
    )

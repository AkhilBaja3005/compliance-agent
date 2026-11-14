"""24-hour background sync scheduler (APScheduler)."""
from __future__ import annotations

from datetime import datetime

from apscheduler.schedulers.background import BackgroundScheduler

from .fetcher import sync_now
from .store import get_store

JOB_ID = "daily-law-sync"
_scheduler: BackgroundScheduler | None = None


def start_scheduler(interval_hours: float = 24, run_immediately: bool = False) -> BackgroundScheduler:
    global _scheduler
    if _scheduler is not None and _scheduler.running:
        return _scheduler
    _scheduler = BackgroundScheduler(daemon=True)
    kwargs = {"next_run_time": datetime.now().astimezone()} if run_immediately else {}  # None would pause the job
    _scheduler.add_job(sync_now, "interval", hours=interval_hours, id=JOB_ID, replace_existing=True, **kwargs)
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

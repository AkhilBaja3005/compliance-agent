"""Dashboard storage, job lifecycle, scheduling, isolation and publication contracts."""
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
import threading
import time
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from src.dashboard.models import Settings, SettingsRecord, Sources
from src.dashboard.service import DashboardService, INTERVALS
from src.schemas.findings import TriagedAuditReport
from src.storage.dashboard import MongoDashboardRepository, SQLiteDashboardRepository, now

A, B = "company_a_finscore", "company_b_voxgen"


def report(company=A, report_id="report-1", assessed_at=None):
    return TriagedAuditReport(tenant_id=company, company_name=company, report_id=report_id,
                             assessed_at=assessed_at or now(), law_index_version="test", overall_readiness="UNKNOWN")


@pytest.fixture(params=["sqlite", "mongodb"])
def repository(request, tmp_path):
    if request.param == "mongodb":
        import mongomock

        return MongoDashboardRepository(mongomock.MongoClient().dashboard_test)
    return SQLiteDashboardRepository(tmp_path / "nested" / "dashboard.sqlite3")


def await_job(repository, company, job_id, expected="succeeded"):
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline:
        job = repository.get_job(company, job_id)
        if job.state in ("succeeded", "failed"):
            assert job.state == expected, job.error
            return job
        time.sleep(.01)
    pytest.fail("Audit worker did not finish")


def test_reports_are_idempotent_scoped_and_ordered_by_assessment(repository):
    base = datetime(2026, 1, 1, tzinfo=timezone.utc)
    for i in range(35):
        repository.save_report(report(report_id=f"r-{i:02}", assessed_at=base + timedelta(hours=i)))
    # Older assessment finishes late; duplicate IDs are immutable, including assessment time.
    repository.save_report(report(report_id="late", assessed_at=base - timedelta(hours=1)))
    repository.save_report(report(report_id="r-00", assessed_at=base + timedelta(days=10)))
    repository.save_report(report(B, "r-34", assessed_at=base))
    recent = repository.recent_reports(A)
    assert len(recent) == 30
    assert [r.report_id for r in recent] == [f"r-{i:02}" for i in range(34, 4, -1)]
    assert repository.get_report(A, "r-00").assessed_at == base
    assert repository.get_report(B, "r-00") is None
    assert repository.get_report(B, "r-34").tenant_id == B
    assert repository.recent_reports("unknown") == []


def test_sqlite_survives_reopening_and_concurrent_publication(tmp_path):
    path = tmp_path / "shared.sqlite3"
    first, second = SQLiteDashboardRepository(path), SQLiteDashboardRepository(path)
    with ThreadPoolExecutor(max_workers=8) as pool:
        list(pool.map(lambda i: (first if i % 2 else second).save_report(report(report_id=f"report-{i}")), range(50)))
    reopened = SQLiteDashboardRepository(path)
    assert len(reopened.recent_reports(A, 100)) == 50
    assert reopened.get_report(A, "report-49").report_id == "report-49"


@pytest.mark.parametrize("backend", ["mongodb", "offline", "unavailable", "index-denied"])
def test_repository_backend_selection_and_visible_fallback(monkeypatch, backend):
    import mongomock
    from src.storage import dashboard

    class DeniedDatabase:
        def __getitem__(self, name):
            raise PermissionError("private connection details")

    store = SimpleNamespace(is_atlas=backend in ("mongodb", "index-denied"),
                            db=DeniedDatabase() if backend == "index-denied" else mongomock.MongoClient().test,
                            error="connection failed" if backend == "unavailable" else None)
    monkeypatch.setattr("src.storage.get_compliance_store", lambda: store)
    repository = dashboard.get_dashboard_repository()
    assert repository.mode == ("mongodb" if backend == "mongodb" else "sqlite")
    assert bool(repository.warning) == (backend in ("unavailable", "index-denied"))
    assert "private connection details" not in str(repository.warning)
    repository.save_report(report())
    assert repository.get_report(A, "report-1") is not None

    # Losing the chosen database later surfaces a failure instead of splitting history.
    def unavailable(_):
        raise OSError("private connection details")

    monkeypatch.setattr(repository, "save_report", unavailable)
    completed = report(report_id="failed-save")
    dashboard.publish_completed_report(completed)
    assert completed.stack_telemetry["dashboard_persistence"]["status"] == "failed"
    assert dashboard.get_dashboard_repository() is repository


def test_repository_jobs_settings_deduplication_and_recovery(repository):
    assert repository.get_settings(A).schedule.enabled is False
    assert repository.get_settings(A).schedule.frequency == "daily"
    settings = SettingsRecord(company_id=A, sources=Sources(github_url="/sources/a"))
    repository.save_settings(settings)
    assert repository.get_settings(A).sources.github_url == "/sources/a"
    assert repository.get_settings(B).sources.github_url is None
    with ThreadPoolExecutor(max_workers=6) as pool:
        results = list(pool.map(lambda _: repository.enqueue(A, settings.sources, "manual"), range(6)))
    assert sum(created for _, created in results) == 1
    assert len({job.job_id for job, _ in results}) == 1
    first = results[0][0]
    assert repository.get_job(B, first.job_id) is None
    first.state, first.started_at = "running", now()
    repository.save_job(first)
    other, _ = repository.enqueue(B, Sources(), "scheduled")
    repository.fail_interrupted()
    for company, job_id in [(A, first.job_id), (B, other.job_id)]:
        job = repository.get_job(company, job_id)
        assert job.state == "failed" and job.finished_at and "restart" in job.error
    replacement, created = repository.enqueue(A, Sources(), "manual")
    assert created and replacement.job_id != first.job_id
    assert repository.latest_job(A).job_id == replacement.job_id


def test_direct_run_audit_publishes_finalized_report(fixtures_dir):
    from src.agents import run_audit
    from src.storage.dashboard import get_dashboard_repository

    result = run_audit(fixtures_dir / A, A)
    stored = get_dashboard_repository().get_report(A, result.report_id)
    assert stored.model_dump() == result.model_dump()
    assert stored.bundle_sha256 and stored.input_coverage and stored.system_inventory
    assert stored.stack_telemetry["dashboard_persistence"]["status"] == "saved"
    assert stored.all_findings()[0].history_status == result.all_findings()[0].history_status


def test_persistence_failure_is_visible_without_breaking_audit(fixtures_dir, monkeypatch, caplog):
    from src.agents import run_audit
    from src.storage.dashboard import get_dashboard_repository, storage_status

    repo = get_dashboard_repository()

    def broken(_):
        raise OSError("private connection secret")

    monkeypatch.setattr(repo, "save_report", broken)
    result = run_audit(fixtures_dir / A, A)
    assert result.report_id and result.all_findings()
    telemetry = result.stack_telemetry["dashboard_persistence"]
    assert telemetry["status"] == "failed"
    assert "OSError" in storage_status(repo, A).persistence_error
    assert "private connection secret" not in str(telemetry) + caplog.text


def test_background_worker_is_serial_and_captures_saved_sources(repository, fixtures_dir):
    started, release = threading.Event(), threading.Event()
    calls = []

    def runner(directory, company_id, **options):
        calls.append((directory, company_id, options))
        started.set()
        assert release.wait(5)
        result = report(company_id, f"report-{len(calls)}")
        repository.save_report(result)
        return result

    service = DashboardService(repository, lambda: [A, B], lambda: fixtures_dir, runner)
    service.start()
    try:
        service.save_settings(A, Settings(sources=Sources(github_url="/saved/repository", confluence_space_key="AI")))
        first = service.enqueue(A)
        assert started.wait(3)
        duplicate = service.enqueue(A)
        assert duplicate.job_id == first.job_id
        second = service.enqueue(B)
        assert repository.get_job(B, second.job_id).state == "queued"
        assert len(calls) == 1
        service.save_settings(A, Settings(sources=Sources(github_url="/changed/repository")))
        release.set()
        done = await_job(repository, A, first.job_id)
        await_job(repository, B, second.job_id)
        assert done.started_at and done.finished_at and done.report_id
        assert calls[0][0] == fixtures_dir / A
        assert calls[0][2]["github_source"] == "/saved/repository"
        assert calls[0][2]["space_key"] == "AI" and calls[0][2]["confluence_source"] == "cloud"
    finally:
        release.set()
        service.stop()


@pytest.mark.parametrize("failure", ["exception", "unpublished", "wrong-tenant"])
def test_worker_failures_preserve_completed_reports(repository, fixtures_dir, failure):
    previous = report(report_id="previous")
    repository.save_report(previous)

    def runner(*args, **kwargs):
        if failure == "exception":
            raise FileNotFoundError("token=secret")
        return report(B if failure == "wrong-tenant" else A, "unpublished")

    service = DashboardService(repository, lambda: [A], lambda: fixtures_dir, runner)
    service.start()
    try:
        job = service.enqueue(A)
        result = await_job(repository, A, job.job_id, "failed")
        assert result.error and "token=secret" not in result.error
        snapshot = service.snapshot(A)
        assert snapshot.latest_report.report_id == previous.report_id
        assert snapshot.latest_job.state == "failed"
    finally:
        service.stop()


def test_schedules_wait_full_interval_change_disable_and_restore(repository, fixtures_dir, monkeypatch):
    from src.dashboard import service as service_module

    current = now()
    monkeypatch.setattr(service_module, "now", lambda: current)
    calls = []
    service = DashboardService(repository, lambda: [A], lambda: fixtures_dir, lambda *a, **k: calls.append(a))
    service.start()
    try:
        assert service.snapshot(A).next_scheduled_run is None
        for frequency in INTERVALS:
            settings = Settings(schedule={"enabled": True, "frequency": frequency})
            record = service.save_settings(A, settings)
            assert record.next_run_at == current + INTERVALS[frequency]
            assert service.snapshot(A).next_scheduled_run == record.next_run_at
            # Editing sources preserves phase.
            current += timedelta(seconds=10)
            settings.sources.github_url = "/saved"
            assert service.save_settings(A, settings).next_run_at == record.next_run_at
        assert calls == []
        service.save_settings(A, Settings())
        assert service.snapshot(A).next_scheduled_run is None
        assert service.scheduler.get_jobs() == []
    finally:
        service.stop()

    # Simulate downtime spanning several missed intervals, and interrupted work.
    anchor = current - timedelta(days=3, hours=1)
    repository.save_settings(SettingsRecord(company_id=A, schedule={"enabled": True, "frequency": "daily"}, next_run_at=anchor))
    abandoned, _ = repository.enqueue(A, Sources(), "manual")
    restored = DashboardService(repository, lambda: [A], lambda: fixtures_dir, lambda *a, **k: calls.append(a))
    restored.start()
    try:
        next_run = restored.snapshot(A).next_scheduled_run
        assert next_run == anchor + timedelta(days=4)
        assert repository.get_settings(A).next_run_at == next_run
        assert repository.get_job(A, abandoned.job_id).state == "failed"
        assert calls == []
    finally:
        restored.stop()


def test_scheduled_callback_queues_saved_sources_and_advances_next_run(repository, fixtures_dir, monkeypatch):
    from src.dashboard import service as service_module

    current = now()
    monkeypatch.setattr(service_module, "now", lambda: current)

    def runner(directory, company_id, **kwargs):
        assert kwargs["github_source"] == "/scheduled"
        result = report(company_id)
        repository.save_report(result)
        return result

    service = DashboardService(repository, lambda: [A], lambda: fixtures_dir, runner)
    service.start()
    try:
        record = service.save_settings(A, Settings(sources=Sources(github_url="/scheduled"), schedule={"enabled": True, "frequency": "hourly"}))
        current = record.next_run_at + timedelta(milliseconds=10)
        service._scheduled(A)
        job = repository.latest_job(A)
        assert job.trigger == "scheduled"
        await_job(repository, A, job.job_id)
        assert repository.get_settings(A).next_run_at == record.next_run_at + timedelta(hours=1)
    finally:
        service.stop()


def test_dashboard_api_ownership_manual_run_and_synchronous_compatibility():
    from src.api import app

    with TestClient(app) as client:
        for path in ("/", "/dashboard/overview", "/dashboard/findings", "/dashboard/static/dashboard.js", "/healthz"):
            assert client.get(path).status_code == 200
        base = f"/dashboard/api/companies/{A}"
        empty = client.get(base + "/snapshot").json()
        assert empty["latest_report"] is None and not empty["settings"]["schedule"]["enabled"]
        assert client.put(base + "/settings", json={"sources": {"github_url": "https://token@github.com/a/b"}}).status_code == 422
        assert client.put(base + "/settings", json={"schedule": {"frequency": "minutely"}}).status_code == 422
        assert client.put(base + "/settings", json={"sources": {"confluence_path": "/a", "confluence_space_key": "B"}}).status_code == 422
        assert client.put(base + "/settings", json={"sources": {"token": "secret"}}).status_code == 422
        queued = client.post(base + "/runs")
        assert queued.status_code == 202
        job_id = queued.json()["job_id"]
        done = await_job(app.state.dashboard.repository, A, job_id)
        snapshot = client.get(base + "/snapshot")
        assert snapshot.headers["cache-control"] == "no-store"
        assert snapshot.json()["latest_report"]["report_id"] == done.report_id
        full = client.get(base + f"/reports/{done.report_id}")
        assert full.status_code == 200 and full.json()["tenant_id"] == A
        other = f"/dashboard/api/companies/{B}"
        assert client.get(other + f"/reports/{done.report_id}").status_code == 404
        assert client.get(other + f"/runs/{job_id}").status_code == 404
        assert client.get(base + "/reports/missing").status_code == 404
        for method, suffix in [("get", "/snapshot"), ("get", "/reports/x"), ("post", "/runs"), ("get", "/runs/x"), ("put", "/settings")]:
            kwargs = {"json": {}} if method == "put" else {}
            assert getattr(client, method)("/dashboard/api/companies/unknown" + suffix, **kwargs).status_code == 404
        sync = client.post("/audit/run", json={"company_id": B})
        assert sync.status_code == 200
        assert client.get(other + "/snapshot").json()["latest_report"]["report_id"] == sync.json()["report_id"]


def test_dashboard_storage_outage_returns_503_and_keeps_health_available(monkeypatch):
    from src.api import app

    with TestClient(app) as client:
        def unavailable(*args):
            raise OSError("secret")

        monkeypatch.setattr(app.state.dashboard.repository, "recent_reports", unavailable)
        response = client.get(f"/dashboard/api/companies/{A}/snapshot")
        assert response.status_code == 503 and "secret" not in response.text
        assert client.get("/healthz").json() == {"status": "ok"}

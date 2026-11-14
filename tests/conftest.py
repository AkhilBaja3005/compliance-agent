import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
FIXTURES = ROOT / "tests" / "fixtures" / "companies"


@pytest.fixture(autouse=True)
def _offline_env(monkeypatch, tmp_path):
    monkeypatch.setenv("BYOM_OFFLINE", "true")
    monkeypatch.setenv("COMPANIES_DIR", str(FIXTURES))
    monkeypatch.setenv("USE_DATABRICKS", "false")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "")  # LLMClient re-reads .env: an empty value stops a developer key from leaking into tests
    monkeypatch.setenv("GRAPHITE_FRAMEWORKS", "ALL")
    monkeypatch.setenv("GRAPHITE_DASHBOARD_DB", str(tmp_path / "dashboard.sqlite3"))
    monkeypatch.setenv("GRAPHITE_AUTH_DISABLED", "true")  # security tests enable keys explicitly
    monkeypatch.delenv("GRAPHITE_API_KEYS", raising=False)
    monkeypatch.delenv("GRAPHITE_DATA_DIR", raising=False)
    monkeypatch.delenv("LAW_FEED_URL", raising=False)
    monkeypatch.delenv("LAW_FEED_FILE", raising=False)
    # engines must run in clean offline-fallback mode regardless of the developer's shell / .env
    for var in ("LINKUP_API_KEY", "MONGODB_URI", "MONGODB_DB_NAME", "MONGODB_DATABASE", "DATABRICKS_HOST", "DATABRICKS_TOKEN",
                "DATABRICKS_WAREHOUSE_ID", "DATABRICKS_SERVING_ENDPOINT", "MLFLOW_TRACKING_URI", "GITHUB_TOKEN",
                "CONFLUENCE_URL", "CONFLUENCE_EMAIL", "CONFLUENCE_USERNAME", "CONFLUENCE_API_TOKEN", "GRAPHITE_HISTORY_FILE"):
        monkeypatch.setenv(var, "")  # blank, not unset: code that reloads .env must not re-fill them from a developer's file
    from src.law_sync import reset_overlay, reset_store, set_scout
    from src.storage import reset_compliance_store, set_compliance_store
    from src.security import limiter

    limiter.reset()
    reset_overlay()
    reset_store()
    set_scout(None)
    reset_compliance_store()
    from src.storage import dashboard

    monkeypatch.setattr(dashboard, "_repositories", {})
    monkeypatch.setattr(dashboard, "_errors", {})
    yield
    reset_overlay()
    reset_store()
    set_scout(None)
    set_compliance_store(None)


@pytest.fixture
def fixtures_dir():
    return FIXTURES

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
    monkeypatch.setenv("AEGIS_FRAMEWORKS", "ALL")
    monkeypatch.setenv("AEGIS_DASHBOARD_DB", str(tmp_path / "dashboard.sqlite3"))
    monkeypatch.delenv("LAW_FEED_URL", raising=False)
    monkeypatch.delenv("LAW_FEED_FILE", raising=False)
    # engines must run in clean offline-fallback mode regardless of the developer's shell / .env
    for var in ("LINKUP_API_KEY", "MONGODB_URI", "MONGODB_DB_NAME", "MONGODB_DATABASE", "DATABRICKS_HOST", "DATABRICKS_TOKEN",
                "DATABRICKS_WAREHOUSE_ID", "DATABRICKS_SERVING_ENDPOINT", "MLFLOW_TRACKING_URI", "GITHUB_TOKEN",
                "CONFLUENCE_URL", "CONFLUENCE_EMAIL", "CONFLUENCE_USERNAME", "CONFLUENCE_API_TOKEN", "AEGIS_HISTORY_FILE"):
        monkeypatch.delenv(var, raising=False)
    from src.law_sync import reset_overlay, reset_store, set_scout
    from src.storage import reset_compliance_store, set_compliance_store

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

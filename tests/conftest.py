import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
FIXTURES = ROOT / "tests" / "fixtures" / "companies"


@pytest.fixture(autouse=True)
def _offline_env(monkeypatch):
    monkeypatch.setenv("BYOM_OFFLINE", "true")
    monkeypatch.setenv("COMPANIES_DIR", str(FIXTURES))
    monkeypatch.setenv("USE_DATABRICKS", "false")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "")  # LLMClient re-reads .env: an empty value stops a developer key from leaking into tests
    monkeypatch.setenv("AEGIS_FRAMEWORKS", "ALL")
    monkeypatch.setenv("AEGIS_AUTH_DISABLED", "true")  # security tests enable keys explicitly
    monkeypatch.delenv("AEGIS_API_KEYS", raising=False)
    monkeypatch.delenv("AEGIS_DATA_DIR", raising=False)
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
    yield
    reset_overlay()
    reset_store()
    set_scout(None)
    set_compliance_store(None)


@pytest.fixture
def fixtures_dir():
    return FIXTURES

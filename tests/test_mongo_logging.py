"""MongoDB fallback reasons reach the server's structured stdout logs."""
import json
import logging
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from pymongo.errors import ConfigurationError, OperationFailure, ServerSelectionTimeoutError

from src.observability import configure_logging
from src.storage.mongo_store import MongoComplianceStore


@pytest.fixture
def server_logging(monkeypatch):
    logger = logging.getLogger("graphite")
    monkeypatch.setattr(logger, "handlers", [])
    monkeypatch.setattr(logger, "level", logging.NOTSET)
    monkeypatch.setattr(logger, "propagate", True)
    def configure():
        configure_logging()
        # Repeated setup must not duplicate each diagnostic.
        configure_logging()

    return configure


@pytest.mark.parametrize("error", [
    ConfigurationError("DNS lookup failed: SRV record does not exist"),
    OperationFailure("Authentication failed", code=18),
    ServerSelectionTimeoutError("SSL handshake failed: certificate verify failed"),
])
def test_mongo_ping_failure_logs_reason_to_stdout(monkeypatch, capsys, server_logging, error):
    server_logging()
    client = Mock()
    client.admin.command.side_effect = error
    monkeypatch.setattr("pymongo.MongoClient", Mock(return_value=client))

    store = MongoComplianceStore(uri="mongodb://cluster.example.test:27017")

    captured = capsys.readouterr()
    assert not captured.err
    record = json.loads(captured.out)
    assert not store.is_atlas and store.error
    assert record["level"] == "WARNING"
    assert "ping" in record["msg"]
    assert type(error).__name__ in record["msg"]
    assert str(error) in record["msg"]
    assert "using in-memory fallback" in record["msg"]


def test_mongo_client_configuration_failure_logs_reason_to_stdout(monkeypatch, capsys, server_logging):
    server_logging()
    monkeypatch.setenv("MONGODB_TIMEOUT_MS", "invalid-timeout")

    store = MongoComplianceStore(uri="mongodb://cluster.example.test:27017")

    record = json.loads(capsys.readouterr().out)
    assert not store.is_atlas
    assert "client configuration" in record["msg"]
    assert "ValueError" in record["msg"] and "invalid-timeout" in record["msg"]


def test_dashboard_index_failure_logs_reason_but_keeps_banner_generic(monkeypatch, capsys, server_logging):
    from src.storage import dashboard

    server_logging()
    monkeypatch.setattr("src.storage.get_compliance_store", lambda: SimpleNamespace(is_atlas=True, db=object()))
    reason = "not authorized to create indexes on dashboard_reports"
    monkeypatch.setattr(dashboard, "MongoDashboardRepository", Mock(side_effect=OperationFailure(reason, code=13)))

    repository = dashboard.get_dashboard_repository()

    captured = capsys.readouterr()
    record = json.loads(captured.out)
    assert not captured.err
    assert repository.mode == "sqlite"
    assert reason in record["msg"] and "OperationFailure" in record["msg"]
    assert "using SQLite" in record["msg"]
    assert reason not in repository.warning

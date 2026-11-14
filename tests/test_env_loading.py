"""Environment file values remain usable by downstream service clients."""
import os

import pytest

from src.agents.llm_client import _load_dotenv


@pytest.mark.parametrize("quote", ["", "'", '"'])
def test_dotenv_loads_mongodb_uri_and_timeout(tmp_path, monkeypatch, quote):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(os, "environ", os.environ.copy())
    monkeypatch.delenv("MONGODB_URI", raising=False)
    monkeypatch.delenv("MONGODB_TIMEOUT_MS", raising=False)
    uri = "mongodb+srv://test:p%40ss%23word@cluster.example.test/?retryWrites=true&w=majority"
    (tmp_path / ".env").write_text(
        f"MONGODB_URI={quote}{uri}{quote}\nMONGODB_TIMEOUT_MS={quote}5000{quote}\n",
        encoding="utf-8",
    )

    _load_dotenv()

    assert os.environ["MONGODB_URI"] == uri
    assert int(os.environ["MONGODB_TIMEOUT_MS"]) == 5000


@pytest.mark.parametrize("existing", ["mongodb://configured.example.test:27017", ""])
def test_dotenv_preserves_existing_environment(tmp_path, monkeypatch, existing):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("MONGODB_URI", existing)
    (tmp_path / ".env").write_text('MONGODB_URI="mongodb://file.example.test:27017"\n', encoding="utf-8")

    _load_dotenv()

    assert os.environ["MONGODB_URI"] == existing

"""Authored tests only; generation of this repository did not execute them."""
import json
from pathlib import Path
from types import SimpleNamespace
import pytest
from fastapi.testclient import TestClient
from app.api import create_app
from app.factory import build_service
from app.schemas import SubmissionRequest


@pytest.fixture
def system():
    service = build_service()
    actor = service.directory.current("atlas-editor")
    token = service.directory.issue_local(actor.subject)
    client = TestClient(create_app(service, local_sessions=True))
    client.headers.update({"Authorization": "Bearer " + token, "X-DemoText-Client": "editor-v1"})
    texts = json.loads((Path(__file__).resolve().parent.parent / "fixtures/texts.json").read_text())
    request = SubmissionRequest(text=texts["editorial"], purpose="business_editorial_review",
                                domain="marketing", language="en", model_version="dtv-1.1")
    yield SimpleNamespace(service=service, actor=actor, client=client, request=request, texts=texts)
    client.close()

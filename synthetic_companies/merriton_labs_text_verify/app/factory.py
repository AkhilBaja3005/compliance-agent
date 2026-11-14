import json
from pathlib import Path
from .api import create_app
from .audit import Audit
from .auth import Directory
from .clock import FixedClock
from .domain import Principal
from .fake_classifier import FakeClassifier
from .fake_queue import FakeQueue
from .memory import MemoryStorage
from .notices import Notices
from .onboarding import Onboarding
from .registry import Registry
from .service import VerifyService


def build_service(*, clock=None, classifier=None, storage=None, jobs=None,
                  directory=None, onboarding=None, registry=None, notices=None) -> VerifyService:
    clock = clock if clock is not None else FixedClock()
    if directory is None:
        directory = Directory([Principal(tenant, tenant + "-" + role, role)
                               for tenant in ("atlas", "birch") for role in ("editor", "admin")]
                              + [Principal("atlas", "synthetic-operator", "operator")])
    if onboarding is None:
        data = json.loads((Path(__file__).resolve().parent.parent / "fixtures" / "participation.json").read_text())
        onboarding = Onboarding(data["records"])
    return VerifyService(storage if storage is not None else MemoryStorage(),
                         classifier if classifier is not None else FakeClassifier(),
                         jobs if jobs is not None else FakeQueue(), clock, directory, onboarding,
                         registry if registry is not None else Registry(),
                         notices if notices is not None else Notices(), Audit(clock))


def create_local_app():
    """Explicit ASGI factory; no application, SDK client or credential is created on import."""
    return create_app(build_service(), local_sessions=True)

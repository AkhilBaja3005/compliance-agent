"""Structured JSON logging with correlation IDs and in-process Prometheus-style metrics."""
from __future__ import annotations

import json
import logging
import threading
import time
import uuid
from collections import defaultdict
from contextvars import ContextVar

request_id_var: ContextVar[str] = ContextVar("request_id", default="-")


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        d = {"ts": time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime(record.created)) + "Z", "level": record.levelname, "logger": record.name,
             "msg": record.getMessage(), "request_id": request_id_var.get()}
        for k in ("method", "path", "status", "duration_ms", "key_id", "tenant", "job_id", "event"):
            if hasattr(record, k):
                d[k] = getattr(record, k)
        if record.exc_info:
            d["exc"] = self.formatException(record.exc_info).splitlines()[-1]
        return json.dumps(d)


def configure_logging(level: str = "INFO") -> None:
    root = logging.getLogger("aegis")
    if any(getattr(h, "_aegis", False) for h in root.handlers):
        return
    h = logging.StreamHandler()
    h.setFormatter(JsonFormatter())
    h._aegis = True  # type: ignore[attr-defined]
    root.addHandler(h)
    root.setLevel(level)
    root.propagate = False


def new_request_id() -> str:
    return uuid.uuid4().hex[:16]


class Metrics:
    def __init__(self):
        self._c: dict[tuple[str, tuple], float] = defaultdict(float)
        self._lock = threading.Lock()

    def inc(self, name: str, value: float = 1.0, **labels):
        with self._lock:
            self._c[(name, tuple(sorted(labels.items())))] += value

    def render(self) -> str:
        with self._lock:
            lines = []
            for (name, labels), v in sorted(self._c.items()):
                lab = "{" + ",".join(f'{k}="{val}"' for k, val in labels) + "}" if labels else ""
                lines.append(f"{name}{lab} {v:g}")
        return "\n".join(lines) + "\n"

    def reset(self):
        with self._lock:
            self._c.clear()


metrics = Metrics()

"""MLflow tracing with a safe no-op fallback when MLflow / Databricks is not configured."""
from __future__ import annotations

import functools
import logging
import os

log = logging.getLogger(__name__)
_configured = False


def tracing_enabled() -> bool:
    return bool(os.getenv("MLFLOW_TRACKING_URI") or (os.getenv("DATABRICKS_HOST") and os.getenv("DATABRICKS_TOKEN")))


def _configure() -> bool:
    global _configured
    if _configured:
        return True
    try:
        import mlflow

        uri = os.getenv("MLFLOW_TRACKING_URI") or "databricks"
        mlflow.set_tracking_uri(uri)
        exp = os.getenv("MLFLOW_EXPERIMENT_NAME")
        if exp:
            mlflow.set_experiment(exp)
        _configured = True
    except Exception as exc:
        log.warning("MLflow tracing unavailable (%s); tracing disabled", exc)
        return False
    return True


def current_trace_id() -> str | None:
    """Trace id of the active MLflow span (inside a traced call), else None."""
    if not tracing_enabled():
        return None
    try:
        import mlflow

        span = mlflow.get_current_active_span()
        return getattr(span, "trace_id", None) if span is not None else None
    except Exception:
        return None


def traced(name: str | None = None, span_type: str = "AGENT"):
    """`@mlflow.trace` when MLflow is configured (checked per call); transparent pass-through otherwise."""

    def deco(fn):
        cache: dict = {}

        @functools.wraps(fn)
        def wrapper(*args, **kwargs):
            if not tracing_enabled() or not _configure():
                return fn(*args, **kwargs)
            if "t" not in cache:
                try:
                    import mlflow

                    cache["t"] = mlflow.trace(name=name or fn.__qualname__, span_type=span_type)(fn)
                except Exception as exc:  # pragma: no cover
                    log.warning("mlflow.trace unavailable: %s", exc)
                    cache["t"] = fn
            return cache["t"](*args, **kwargs)

        wrapper.__wrapped_traced__ = True
        return wrapper

    return deco

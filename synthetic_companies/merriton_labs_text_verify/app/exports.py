import json


def export_advice(envelope: dict) -> str:
    """Portable JSON advice includes the full current notice, model and limitations."""
    return json.dumps({"format": "demotext-advice-1", **envelope}, ensure_ascii=False, indent=2)

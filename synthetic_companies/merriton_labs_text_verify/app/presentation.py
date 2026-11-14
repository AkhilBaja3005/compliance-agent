from .domain import Submission
from .notices import Notices
from .registry import Model

ADVICE = "Editorial advice only. This is not a verdict about an author or evidence for sanctions."


def result_envelope(record: Submission, model: Model, notices: Notices, simulated: bool) -> dict:
    # Recompose on every delivery; cached inference never freezes notices or limitations.
    limitations = list(dict.fromkeys((*record.analysis_limitations, *model.limitations)))
    return {
        "id": record.id, "state": record.state, "created_at": record.created_at.isoformat(),
        "notice": notices.current(), "submitted_notice_version": record.submitted_notice_version,
        "mode": "deterministic_simulation" if simulated else "managed_classifier",
        "model": {"version": model.version, "evaluation_id": model.evaluation_id,
                  "supported_domains": model.domains, "supported_languages": model.languages},
        "limitations": limitations, "advice": ADVICE,
        "analysis": record.output.model_dump() if record.output else None,
        "error_code": record.error_code, "editorial_judgment": record.judgment,
        "attempt": record.attempt,
    }

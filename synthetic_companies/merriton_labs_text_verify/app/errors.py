class ProductError(Exception):
    def __init__(self, code: str, status: int = 400):
        super().__init__(code)
        self.code = code
        self.status = status


class ProviderFailure(ProductError):
    def __init__(self, code: str = "provider_unavailable"):
        super().__init__(code, 503)


MESSAGES = {
    "unauthorized": "Select an authorized session before continuing.",
    "forbidden": "This role or onboarding record does not allow this action.",
    "not_found": "Submission not found in this workspace.",
    "deleted": "This submission was deleted and cannot be retried.",
    "purpose_rejected": "Only business editorial review is supported. Do not assess people.",
    "model_unavailable": "This model release is unavailable for the requested domain.",
    "invalid_input": "Check the input, language, purpose, model and request key.",
    "idempotency_conflict": "Use a new request key for a different request.",
    "provider_timeout": "The classifier timed out. No analysis was inferred.",
    "provider_unavailable": "The classifier is unavailable. No analysis was inferred.",
    "provider_contract": "The classifier returned an invalid response. No analysis was inferred.",
    "queue_unavailable": "Work could not be delivered. Retry this submission explicitly.",
    "not_ready": "An editorial judgment requires a completed advisory analysis.",
    "internal_error": "The request could not be completed safely.",
}


def safe_error(error: ProductError) -> dict:
    code = error.code if error.code in MESSAGES else "internal_error"
    return {"code": code, "message": MESSAGES[code]}

import re
from .errors import ProductError, ProviderFailure
from .schemas import SubmissionRequest, ClassifierOutput
from .registry import Registry, Model


def validate_use(request: SubmissionRequest, registry: Registry) -> Model:
    # Actual per-item purpose, always before cache lookup or inference.
    if request.purpose != "business_editorial_review":
        raise ProductError("purpose_rejected", 422)
    if not request.text.strip() or len(request.text.encode("utf-8")) > 40000:
        raise ProductError("invalid_input", 422)
    return registry.require(request.model_version, request.domain)


def validate_key(key: str) -> None:
    if not re.fullmatch(r"[A-Za-z0-9_-]{8,80}", key):
        raise ProductError("invalid_input", 422)


def normalize_output(output: ClassifierOutput, request: SubmissionRequest) -> ClassifierOutput:
    if output.model_version != request.model_version:
        raise ProviderFailure("provider_contract")
    if output.state == "abstained":
        if output.score is not None or output.reason == "classified":
            raise ProviderFailure("provider_contract")
        return output
    if output.score is None or output.reason != "classified":
        raise ProviderFailure("provider_contract")
    if output.confidence < 0.65:
        return ClassifierOutput(model_version=output.model_version, state="abstained",
                                confidence=output.confidence, reason="low_confidence")
    return output

from .schemas import SubmissionRequest, ClassifierOutput
from .errors import ProviderFailure


class FakeClassifier:
    """Deterministic simulation; these values have no detector validity."""
    simulated = True

    def __init__(self):
        self.calls = 0
        self.failure: str | None = None

    def classify(self, request: SubmissionRequest) -> ClassifierOutput:
        self.calls += 1
        if self.failure:
            raise ProviderFailure(self.failure)
        if len(request.text.split()) < 20:
            return ClassifierOutput(model_version=request.model_version, state="abstained",
                                    confidence=0.4, reason="low_confidence")
        score = 0.72 if request.model_version == "dtv-1.0" else 0.68
        return ClassifierOutput(model_version=request.model_version, state="scored", score=score,
                                confidence=0.76, reason="classified")

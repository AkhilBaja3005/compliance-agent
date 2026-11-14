import json
from typing import Protocol, Any
from botocore.exceptions import BotoCoreError, ClientError, ReadTimeoutError, ConnectTimeoutError
from pydantic import ValidationError
from .errors import ProviderFailure
from .schemas import SubmissionRequest, ClassifierOutput
from .validation import normalize_output


class RuntimeClient(Protocol):
    def invoke_endpoint(self, **kwargs: Any) -> dict: ...


class SageMakerClassifier:
    """Specialised classifier endpoint, never a general-purpose LLM prompt."""
    simulated = False

    def __init__(self, client: RuntimeClient, endpoints: dict[str, str]):
        self.client = client
        self.endpoints = dict(endpoints)

    def classify(self, request: SubmissionRequest) -> ClassifierOutput:
        endpoint = self.endpoints.get(request.model_version)
        if not endpoint:
            raise ProviderFailure("provider_contract")
        stream = None
        try:
            response = self.client.invoke_endpoint(
                EndpointName=endpoint, ContentType="application/json", Accept="application/json",
                Body=json.dumps({"contract_version": "1", "text": request.text,
                                 "language": request.language, "domain": request.domain,
                                 "model_version": request.model_version}).encode("utf-8"))
            stream = response["Body"]
            if response.get("ContentType", "").split(";")[0] != "application/json":
                raise ProviderFailure("provider_contract")
            raw = stream.read(8193)
            if len(raw) > 8192:
                raise ProviderFailure("provider_contract")
            output = ClassifierOutput.model_validate_json(raw)
            return normalize_output(output, request)
        except (ReadTimeoutError, ConnectTimeoutError, TimeoutError):
            raise ProviderFailure("provider_timeout") from None
        except (ClientError, BotoCoreError, OSError):
            raise ProviderFailure() from None
        except (ValidationError, ValueError, KeyError, TypeError):
            raise ProviderFailure("provider_contract") from None
        finally:
            if stream is not None:
                stream.close()

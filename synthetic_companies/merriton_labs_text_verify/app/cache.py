import hashlib
import json
from .schemas import SubmissionRequest


def input_digest(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def cache_key(tenant: str, request: SubmissionRequest) -> str:
    return json.dumps([tenant, request.model_version, request.domain, request.language,
                       input_digest(request.text)], separators=(",", ":"))


def request_fingerprint(items: list[SubmissionRequest]) -> str:
    encoded = json.dumps([r.model_dump() for r in items], sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()

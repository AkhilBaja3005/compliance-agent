from typing import Literal
from pydantic import BaseModel, ConfigDict, Field


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class SubmissionRequest(StrictModel):
    text: str = Field(min_length=40, max_length=20000)
    purpose: str = Field(min_length=1, max_length=80)
    domain: Literal["marketing", "business_article"]
    language: str = Field(pattern=r"^[a-z]{2}$")
    model_version: str = Field(min_length=1, max_length=40)


class BatchRequest(StrictModel):
    items: list[SubmissionRequest] = Field(min_length=1, max_length=10)


class ReviewRequest(StrictModel):
    decision: Literal["retain_flag", "dismiss_flag"]


class ClassifierOutput(StrictModel):
    model_version: str
    state: Literal["scored", "abstained"]
    score: float | None = Field(default=None, ge=0, le=1, allow_inf_nan=False)
    confidence: float = Field(ge=0, le=1, allow_inf_nan=False)
    reason: Literal["classified", "low_confidence", "unsupported_language"]


class SessionRequest(StrictModel):
    identity: Literal["atlas-editor", "atlas-admin", "birch-editor", "birch-admin"]

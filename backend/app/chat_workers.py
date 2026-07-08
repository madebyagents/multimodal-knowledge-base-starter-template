"""Hidden worker result contracts for DanteDash chat orchestration."""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field, ValidationError


class SupportingQuote(BaseModel):
    source_id: str
    quote: str = Field(min_length=1, max_length=500)


class WorkerClaim(BaseModel):
    claim: str = Field(min_length=1)
    source_ids: list[str] = Field(min_length=1)
    supporting_quotes: list[SupportingQuote] = Field(default_factory=list)
    confidence: float = Field(ge=0.0, le=1.0)


class MediaHandle(BaseModel):
    source_id: str
    page: int | None = None
    timestamp_range: str | None = None
    figure_id: str | None = None


class WorkerResult(BaseModel):
    status: Literal["ok", "partial", "insufficient", "error"]
    assigned_subtask: str = Field(min_length=1)
    salient_claims: list[WorkerClaim] = Field(default_factory=list)
    relevance: Literal["high", "medium", "low", "none"]
    gaps: list[str] = Field(default_factory=list)
    media_handles: list[MediaHandle] = Field(default_factory=list)
    query_used: str = ""
    reason: str = ""


class JudgeDimensionNotes(BaseModel):
    grounding: str = ""
    citation_accuracy: str = ""
    faithfulness: str = ""
    completeness: str = ""
    refusal_calibration: str = ""


class JudgeResult(BaseModel):
    score: float = Field(ge=0.0, le=1.0)
    verdict: Literal["pass", "fail"]
    dimension_notes: JudgeDimensionNotes
    revision_notes: list[str] = Field(default_factory=list)
    unknown: bool = False
    iteration: int = Field(ge=0)


def validate_worker_result(payload: object) -> WorkerResult:
    """Validate a hidden worker payload before any principal can consume it."""
    try:
        return WorkerResult.model_validate(payload)
    except ValidationError:
        raise


def validate_judge_result(payload: object) -> JudgeResult:
    """Validate a hidden judge payload before it can trigger repair."""
    try:
        return JudgeResult.model_validate(payload)
    except ValidationError:
        raise

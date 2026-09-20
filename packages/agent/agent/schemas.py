"""Structured outputs the LLM must produce. Pydantic keeps nodes honest."""

from enum import Enum

from pydantic import BaseModel, Field


class HypothesisStatus(str, Enum):
    open = "open"
    confirmed = "confirmed"
    refuted = "refuted"
    inconclusive = "inconclusive"


class Confidence(str, Enum):
    low = "low"
    medium = "medium"
    high = "high"


class Citation(BaseModel):
    """Every claim must point at something the tools actually returned."""

    tool: str
    source_ref: str = Field(description="log id, commit SHA + path, query text, or metric window")
    excerpt: str = Field(max_length=2000)


class Triage(BaseModel):
    error_signature: str
    affected_endpoints: list[str]
    time_window_start: str
    time_window_end: str
    severity: str


class Hypothesis(BaseModel):
    id: str
    statement: str
    category: str = Field(
        description="bad_deploy | schema_change | resource_config | config_secret | "
        "performance | dependency | config | external | concurrency"
    )
    status: HypothesisStatus = HypothesisStatus.open
    confidence: float = Field(ge=0, le=1, default=0.3)
    evidence_for: list[Citation] = []
    evidence_against: list[Citation] = []
    next_check: str | None = Field(default=None, description="what tool call would test this")


class HypothesisSet(BaseModel):
    hypotheses: list[Hypothesis] = Field(min_length=3, max_length=5)


class Evaluation(BaseModel):
    hypothesis_id: str
    status: HypothesisStatus
    confidence: float = Field(ge=0, le=1)
    new_evidence_for: list[Citation] = []
    new_evidence_against: list[Citation] = []
    reasoning: str


class FixProposal(BaseModel):
    summary: str
    diff_or_config_change: str
    rollback: str
    verified: bool = False


class Report(BaseModel):
    summary: str
    customer_impact: str
    timeline: list[str]
    root_cause: str
    confidence: Confidence
    supporting_evidence: list[Citation]
    ruled_out: list[str]
    fix: FixProposal
    unchecked_areas: list[str]
    is_external: bool = Field(description="True when the cause is outside our code/config")

"""Structured outputs the LLM must produce. Pydantic keeps nodes honest and
keeps outputs short (every field here costs output tokens)."""

from enum import Enum
from typing import Any

from pydantic import BaseModel, Field, model_validator


def _limit(field) -> int | None:
    for m in field.metadata:
        if (n := getattr(m, "max_length", None)) is not None:
            return n
    return None


class Lenient(BaseModel):
    """Length caps guide the model (and keep outputs cheap) but must never fail
    a run: over-long strings and lists are trimmed instead of rejected."""

    @model_validator(mode="before")
    @classmethod
    def _trim(cls, data: Any) -> Any:
        if not isinstance(data, dict):
            return data
        out = dict(data)
        for name, field in cls.model_fields.items():
            value, cap = out.get(name), _limit(field)
            if cap is None or value is None:
                continue
            if isinstance(value, str) and len(value) > cap:
                out[name] = value[: cap - 1].rstrip() + "…"
            elif isinstance(value, list) and len(value) > cap:
                out[name] = value[:cap]
        return out


class HypothesisStatus(str, Enum):
    open = "open"
    confirmed = "confirmed"
    refuted = "refuted"
    inconclusive = "inconclusive"


class Confidence(str, Enum):
    low = "low"
    medium = "medium"
    high = "high"


class Citation(Lenient):
    """Every claim must point at something a tool actually returned."""

    tool: str
    source_ref: str = Field(description="log id, commit sha, metric name+ts, query, or event ref")
    excerpt: str = Field(max_length=300, description="short quote of the evidence")


class Triage(Lenient):
    error_signature: str = Field(description="one line: what is failing, e.g. '500s on POST /checkout'")
    affected_endpoints: list[str]
    started_at: str | None = Field(description="ISO time the incident began if stated, else null")
    severity: str = Field(description="low | medium | high | critical")


class Hypothesis(Lenient):
    id: str = Field(description="H1, H2, ...")
    statement: str = Field(max_length=160)
    category: str = Field(
        description="bad_deploy | schema_change | resource_config | config_secret | "
        "performance | dependency | config | external | concurrency"
    )
    status: HypothesisStatus = HypothesisStatus.open
    confidence: float = Field(ge=0, le=1, default=0.3)
    evidence_for: list[Citation] = []
    evidence_against: list[Citation] = []


class HypothesisSet(Lenient):
    hypotheses: list[Hypothesis] = Field(min_length=3, max_length=5)


class HypothesisUpdate(Lenient):
    id: str
    status: HypothesisStatus
    confidence: float = Field(ge=0, le=1)
    evidence_for: list[Citation] = []
    evidence_against: list[Citation] = []


class ToolCall(Lenient):
    tool: str = Field(description="search_logs | get_metrics | get_deploy_events | list_commits | get_commit_diff | query_database")
    args: dict = Field(default_factory=dict)
    tests_hypothesis: str = Field(description="hypothesis id this call tests")
    why: str = Field(max_length=120)


class Step(Lenient):
    """One reasoning step: evaluate what the last tool returned, then either
    call another tool or conclude. Merging both into one call halves LLM calls."""

    updates: list[HypothesisUpdate] = Field(default=[], description="hypotheses changed by the last result")
    next_call: ToolCall | None = Field(default=None, description="null when concluding")
    conclude: bool = Field(default=False, description="true when a hypothesis is confirmed by >=2 sources or nothing is left to check")
    note: str = Field(max_length=160, description="one line shown on the live timeline")


class FixProposal(Lenient):
    summary: str = Field(max_length=200)
    change: str = Field(description="proposed diff or config change; may be empty for external causes")
    rollback: str = Field(max_length=200)


class Report(Lenient):
    summary: str = Field(max_length=400)
    customer_impact: str = Field(max_length=200)
    timeline: list[str] = Field(max_length=6)
    root_cause: str = Field(max_length=300)
    confidence: Confidence
    supporting_evidence: list[Citation]
    ruled_out: list[str] = Field(description="'H1: statement - why'")
    fix: FixProposal
    unchecked_areas: list[str]
    is_external: bool = Field(description="true when the cause is outside our code/config")

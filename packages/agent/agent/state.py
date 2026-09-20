"""LangGraph state (plan section 4)."""

from typing import Annotated, TypedDict

from langgraph.graph.message import add_messages

from agent.schemas import Evaluation, Hypothesis, Report, Triage


class ToolCallRecord(TypedDict):
    tool: str
    args: dict
    output_preview: str
    latency_ms: float
    error: str | None


class Budget(TypedDict):
    max_steps: int
    max_tokens: int
    max_seconds: int
    steps: int
    tokens: int
    started_at: float


class InvestigationState(TypedDict, total=False):
    # inputs
    run_id: str
    incident_title: str
    incident_description: str

    # working memory
    messages: Annotated[list, add_messages]
    triage: Triage | None
    hypotheses: list[Hypothesis]
    selected_hypothesis_id: str | None
    evaluations: list[Evaluation]
    tool_calls: list[ToolCallRecord]
    budget: Budget

    # outputs
    report: Report | None
    approval: str | None  # approved | edited | rejected
    github_issue_url: str | None
    stop_reason: str | None

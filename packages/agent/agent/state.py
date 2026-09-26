"""LangGraph state. The state IS the agent's memory: each LLM call sees a
compact rendering of it (the "case file"), never the raw chat history."""

from typing import TypedDict

from agent.schemas import Hypothesis, Report, Triage


class ToolRecord(TypedDict):
    step: int
    tool: str
    args: dict
    tests_hypothesis: str
    why: str
    summary: str  # compact rendering shown to the model
    refs: list[str]  # citable source_refs this call produced
    latency_ms: float
    error: str | None


class Usage(TypedDict):
    calls: int
    input_tokens: int
    output_tokens: int
    cost_usd: float


class Budget(TypedDict):
    max_steps: int
    max_tokens: int
    max_seconds: int
    max_cost_usd: float
    started_at: float


class InvestigationState(TypedDict, total=False):
    # inputs
    run_id: str
    incident_title: str
    incident_description: str
    incident_created_at: str

    # working memory
    triage: Triage | None
    hypotheses: list[Hypothesis]
    tool_calls: list[ToolRecord]
    pending_call: dict | None  # ToolCall chosen by the last step
    step: int
    last_note: str
    usage: Usage
    budget: Budget

    # outputs
    report: Report | None
    stop_reason: str | None
    approval: str | None  # approved | edited | rejected
    github_issue_url: str | None

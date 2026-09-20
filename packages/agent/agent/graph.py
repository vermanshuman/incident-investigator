"""The investigation graph (plan section 4).

intake -> triage -> generate_hypotheses -> select_hypothesis -> gather_evidence
      -> evaluate -> (loop | propose_fix) -> write_report -> [interrupt] -> create_github_issue
"""

from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.graph import END, StateGraph

from agent.guardrails import budget_exceeded
from agent.nodes import (
    create_github_issue,
    evaluate,
    gather_evidence,
    generate_hypotheses,
    intake,
    propose_fix,
    select_hypothesis,
    triage,
    write_report,
)
from agent.schemas import HypothesisStatus
from agent.state import InvestigationState

MIN_INDEPENDENT_SOURCES = 2


def _enough_evidence(state: InvestigationState) -> str:
    """Stopping rule: a confirmed hypothesis backed by >=2 independent sources,
    or the budget is gone."""
    reason = budget_exceeded(state["budget"])
    if reason:
        return "stop"

    for h in state.get("hypotheses", []):
        if h.status == HypothesisStatus.confirmed:
            sources = {c.tool for c in h.evidence_for}
            if len(sources) >= MIN_INDEPENDENT_SOURCES:
                return "stop"

    # Loop detection: nothing left to check
    if all(h.status != HypothesisStatus.open for h in state.get("hypotheses", [])):
        return "stop"
    return "continue"


def build_graph(checkpointer: BaseCheckpointSaver | None = None):
    g = StateGraph(InvestigationState)

    g.add_node("intake", intake)
    g.add_node("triage", triage)
    g.add_node("generate_hypotheses", generate_hypotheses)
    g.add_node("select_hypothesis", select_hypothesis)
    g.add_node("gather_evidence", gather_evidence)
    g.add_node("evaluate", evaluate)
    g.add_node("propose_fix", propose_fix)
    g.add_node("write_report", write_report)
    g.add_node("create_github_issue", create_github_issue)

    g.set_entry_point("intake")
    g.add_edge("intake", "triage")
    g.add_edge("triage", "generate_hypotheses")
    g.add_edge("generate_hypotheses", "select_hypothesis")
    g.add_edge("select_hypothesis", "gather_evidence")
    g.add_edge("gather_evidence", "evaluate")
    g.add_conditional_edges(
        "evaluate", _enough_evidence, {"continue": "select_hypothesis", "stop": "propose_fix"}
    )
    g.add_edge("propose_fix", "write_report")
    g.add_edge("write_report", "create_github_issue")
    g.add_edge("create_github_issue", END)

    # Human approval gate: the graph pauses before the only write action.
    return g.compile(checkpointer=checkpointer, interrupt_before=["create_github_issue"])

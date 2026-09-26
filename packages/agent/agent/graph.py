r"""The investigation graph.

intake -> triage -> generate_hypotheses -> decide --(tool)--> run_tool --> decide ...
                                              \--(conclude)--> write_report -> [INTERRUPT] -> create_github_issue
"""

from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.graph import END, StateGraph

from agent.nodes import (
    create_github_issue,
    decide,
    generate_hypotheses,
    intake,
    route_after_decide,
    run_tool_node,
    triage,
    write_report,
)
from agent.state import InvestigationState


def build_graph(checkpointer: BaseCheckpointSaver | None = None):
    g = StateGraph(InvestigationState)
    g.add_node("intake", intake)
    g.add_node("triage", triage)
    g.add_node("generate_hypotheses", generate_hypotheses)
    g.add_node("decide", decide)
    g.add_node("run_tool", run_tool_node)
    g.add_node("write_report", write_report)
    g.add_node("create_github_issue", create_github_issue)

    g.set_entry_point("intake")
    g.add_edge("intake", "triage")
    g.add_edge("triage", "generate_hypotheses")
    g.add_edge("generate_hypotheses", "decide")
    g.add_conditional_edges("decide", route_after_decide, {"run_tool": "run_tool", "write_report": "write_report"})
    g.add_edge("run_tool", "decide")
    g.add_edge("write_report", "create_github_issue")
    g.add_edge("create_github_issue", END)

    # Human approval gate: the graph pauses before the only write action.
    return g.compile(checkpointer=checkpointer, interrupt_before=["create_github_issue"])

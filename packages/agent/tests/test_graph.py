from agent.graph import build_graph
from agent.guardrails import new_budget


def test_graph_stops_at_approval_gate():
    graph = build_graph()
    state = {
        "run_id": "t",
        "incident_title": "t",
        "incident_description": "500s on /checkout",
        "hypotheses": [],
        "evaluations": [],
        "tool_calls": [],
        "budget": new_budget(25, 150000, 300),
    }
    final = graph.invoke(state, {"configurable": {"thread_id": "t"}})
    assert final["report"] is not None
    assert final["report"].root_cause == "Bad deploy"
    # interrupt_before means the issue node has not run
    assert final.get("github_issue_url") is None

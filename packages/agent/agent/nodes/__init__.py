"""Graph nodes. Each takes InvestigationState and returns a partial update.

Phase 0: stubs with the right signatures so the graph compiles.
Phase 3: real LLM + MCP tool calls.
"""

from agent.nodes.stubs import (
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

__all__ = [
    "create_github_issue",
    "evaluate",
    "gather_evidence",
    "generate_hypotheses",
    "intake",
    "propose_fix",
    "select_hypothesis",
    "triage",
    "write_report",
]

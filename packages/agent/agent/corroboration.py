"""When is a hypothesis actually confirmed?

Counting "two different tools" is not enough: two symptom tools agree that
something is broken without ever saying what broke it. The pool-exhaustion
scenario exposed this - a QueuePool error plus a db_pool_usage spike look like
two sources, but the culprit was a config commit nobody had looked at.

So a confirmation needs evidence from both sides:
  symptom - what users experience (logs, metrics, database rows)
  change  - what we did to cause it (deploys, commits, diffs)

The exception is a genuinely external cause: when the change tools have been
queried and returned nothing, "nothing changed" IS the change-side evidence,
and symptom evidence alone confirms it. That keeps "not our bug" a reachable
conclusion instead of an impossible one.
"""

from __future__ import annotations

from agent.schemas import Hypothesis, HypothesisStatus
from agent.state import InvestigationState

SYMPTOM_TOOLS = {"search_logs", "get_metrics", "query_database"}
CHANGE_TOOLS = {"get_deploy_events", "list_commits", "get_commit_diff"}


def change_history_checked(state: InvestigationState) -> bool:
    return any(c["tool"] in CHANGE_TOOLS and not c["error"] for c in state.get("tool_calls", []))


def change_history_empty(state: InvestigationState) -> bool:
    """True when every change tool we ran found nothing - the external signal."""
    runs = [c for c in state.get("tool_calls", []) if c["tool"] in CHANGE_TOOLS and not c["error"]]
    return bool(runs) and all(not c["refs"] for c in runs)


def missing_side(hypothesis: Hypothesis, state: InvestigationState) -> str | None:
    """Which side of the evidence is still missing, or None when corroborated."""
    tools = {c.tool for c in hypothesis.evidence_for}
    if not tools & SYMPTOM_TOOLS:
        return "symptom"
    if not tools & CHANGE_TOOLS:
        # "nothing was deployed" counts as the change side, once actually checked
        return None if change_history_empty(state) else "change"
    return None


def corroborated(state: InvestigationState, hypotheses: list[Hypothesis]) -> list[Hypothesis]:
    return [
        h for h in hypotheses
        if h.status == HypothesisStatus.confirmed and missing_side(h, state) is None
    ]


def pending_confirmations(state: InvestigationState, hypotheses: list[Hypothesis]) -> list[tuple[Hypothesis, str]]:
    """Hypotheses the model called confirmed that still need the other side."""
    out = []
    for h in hypotheses:
        if h.status != HypothesisStatus.confirmed:
            continue
        side = missing_side(h, state)
        if side:
            out.append((h, side))
    return out


def next_missing_side_call(state: InvestigationState, side: str) -> dict | None:
    """The tool call the loop makes on its own when a confirmation is one-sided
    and the model offered no next step. Deterministic and cheap: no extra LLM
    call, and it guarantees the missing side actually gets checked."""
    called = {c["tool"] for c in state.get("tool_calls", [])}
    ladder = (
        [("get_deploy_events", {}), ("list_commits", {"limit": 10})]
        if side == "change"
        else [("search_logs", {"level": "ERROR"}), ("get_metrics", {"metric": "error_rate"})]
    )
    for tool, args in ladder:
        if tool not in called:
            return {"tool": tool, "args": args, "tests_hypothesis": "",
                    "why": f"corroboration rule: {side} evidence is still missing"}
    return None


def nudge(pending: list[tuple[Hypothesis, str]], state: InvestigationState) -> str:
    """Instruction appended to the next step prompt when a confirmation is
    one-sided. Kept short: it is only sent while a gap exists."""
    lines = []
    for h, side in pending:
        if side == "change":
            what = ("what changed - call get_deploy_events, then list_commits or get_commit_diff, "
                    "and cite the commit or config that caused it (if nothing was deployed, that "
                    "itself is the answer and points to an external cause)")
        else:
            what = ("the symptom in production - call search_logs, get_metrics or query_database "
                    "and cite the error or metric users actually hit")
        lines.append(f"{h.id} is not corroborated yet: you still need evidence of {what}.")
    return "\n\nBefore concluding: " + " ".join(lines)

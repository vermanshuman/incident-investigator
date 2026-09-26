"""Run an investigation and emit events per node (the live timeline feed)."""

from __future__ import annotations

import os
import uuid
from collections.abc import Callable
from typing import Any

from langgraph.checkpoint.memory import MemorySaver
from langgraph.checkpoint.serde.jsonplus import JsonPlusSerializer

from agent.graph import build_graph
from agent.guardrails import new_budget
from agent.state import InvestigationState

Event = dict[str, Any]

# Our Pydantic state types must be allow-listed for checkpoint (de)serialisation.
SERDE = JsonPlusSerializer(allowed_msgpack_modules=[
    ("agent.schemas", n) for n in ("Triage", "Hypothesis", "Citation", "Report", "FixProposal",
                                   "HypothesisStatus", "Confidence")
])


def initial_state(title: str, description: str, run_id: str | None = None, created_at: str | None = None) -> InvestigationState:
    return InvestigationState(
        run_id=run_id or uuid.uuid4().hex[:12],
        incident_title=title,
        incident_description=description,
        incident_created_at=created_at,
        budget=new_budget(
            int(os.getenv("AGENT_MAX_STEPS", "12")),
            int(os.getenv("AGENT_MAX_TOKENS", "150000")),
            int(os.getenv("AGENT_MAX_SECONDS", "300")),
            float(os.getenv("AGENT_MAX_COST_USD", "0.10")),
        ),
    )


def investigate(title: str, description: str, on_event: Callable[[Event], None] | None = None,
                thread_id: str | None = None, checkpointer=None) -> InvestigationState:
    """Run until the approval gate. Returns the final state (report included)."""
    graph = build_graph(checkpointer or MemorySaver(serde=SERDE))  # Phase 5 swaps in a Postgres saver
    state = initial_state(title, description)
    config = {"configurable": {"thread_id": thread_id or state["run_id"]}}
    seq = 0
    for chunk in graph.stream(state, config, stream_mode="updates"):
        for node, update in chunk.items():
            if not isinstance(update, dict):  # e.g. "__interrupt__" marker at the approval gate
                continue
            seq += 1
            ev: Event = {"seq": seq, "node": node, "note": update.get("last_note", "")}
            if node == "run_tool" and update.get("tool_calls"):
                ev["tool_call"] = update["tool_calls"][-1]
            if "hypotheses" in update:
                ev["hypotheses"] = [h.model_dump() for h in update["hypotheses"]]
            if "usage" in update:
                ev["usage"] = update["usage"]
            if update.get("report"):
                ev["report"] = update["report"].model_dump()
            if update.get("stop_reason"):
                ev["stop_reason"] = update["stop_reason"]
            if on_event:
                on_event(ev)
    return graph.get_state(config).values

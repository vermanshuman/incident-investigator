"""Run an investigation and emit events per node (the live timeline feed).

A run pauses at the approval gate and may sit there for hours, so the graph
state is written to a durable checkpointer: the process can restart and the
run still resumes where it stopped.
"""

from __future__ import annotations

import os
import sqlite3
import uuid
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

from langgraph.checkpoint.memory import MemorySaver
from langgraph.checkpoint.serde.jsonplus import JsonPlusSerializer
from langgraph.checkpoint.sqlite import SqliteSaver

from agent.graph import build_graph
from agent.guardrails import new_budget
from agent.state import InvestigationState

Event = dict[str, Any]

# Our Pydantic state types must be allow-listed for checkpoint (de)serialisation.
SERDE = JsonPlusSerializer(allowed_msgpack_modules=[
    ("agent.schemas", n) for n in ("Triage", "Hypothesis", "Citation", "Report", "FixProposal",
                                   "HypothesisStatus", "Confidence")
])


@contextmanager
def checkpointer() -> Iterator[Any]:
    """Durable when AGENT_CHECKPOINT_DB is set, in-memory otherwise (tests).

    Postgres is the production choice; SQLite keeps the local setup to one
    file and needs no server.
    """
    path = os.getenv("AGENT_CHECKPOINT_DB")
    if not path:
        yield MemorySaver(serde=SERDE)
        return
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    # The graph runs in a worker thread, so the connection must not be bound
    # to the thread that opened it.
    conn = sqlite3.connect(path, check_same_thread=False)
    try:
        saver = SqliteSaver(conn)
        saver.serde = SERDE
        saver.setup()
        yield saver
    finally:
        conn.close()


def initial_state(title: str, description: str, run_id: str | None = None,
                  created_at: str | None = None) -> InvestigationState:
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


def _event(seq: int, node: str, update: dict) -> Event:
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
    if update.get("github_issue_url"):
        ev["github_issue_url"] = update["github_issue_url"]
    return ev


def _drain(graph, inputs, config, on_event: Callable[[Event], None] | None, seq: int) -> int:
    for chunk in graph.stream(inputs, config, stream_mode="updates"):
        for node, update in chunk.items():
            if not isinstance(update, dict):  # "__interrupt__" marker at the gate
                continue
            seq += 1
            if on_event:
                on_event(_event(seq, node, update))
    return seq


def investigate(title: str, description: str, on_event: Callable[[Event], None] | None = None,
                thread_id: str | None = None, saver=None) -> InvestigationState:
    """Run until the approval gate. Returns the state, report included."""
    state = initial_state(title, description, run_id=thread_id)
    config = {"configurable": {"thread_id": thread_id or state["run_id"]}}
    if saver is not None:
        graph = build_graph(saver)
        _drain(graph, state, config, on_event, 0)
        return graph.get_state(config).values
    with checkpointer() as cp:
        graph = build_graph(cp)
        _drain(graph, state, config, on_event, 0)
        return graph.get_state(config).values


def resume(thread_id: str, approved: bool, report_overrides: dict | None = None,
           on_event: Callable[[Event], None] | None = None, start_seq: int = 0,
           saver=None) -> InvestigationState:
    """Continue a run that is paused at the approval gate.

    `approved=False` stops without taking the write action. Edits a reviewer
    made to the report are applied to the checkpointed state first, so the
    issue that gets opened is the text they actually approved.
    """
    config = {"configurable": {"thread_id": thread_id}}

    def run(graph) -> InvestigationState:
        snapshot = graph.get_state(config)
        if not snapshot.values:
            raise ValueError(f"no checkpoint for run {thread_id}")
        updates: dict = {"approval": "approved" if approved else "rejected"}
        current = snapshot.values.get("report")
        if report_overrides and current is not None:
            # Re-validate rather than model_copy: a reviewer's edits are raw
            # input, and the fields they touch (confidence, lists) are typed.
            updates["report"] = type(current).model_validate(
                {**current.model_dump(), **report_overrides}
            )
        graph.update_state(config, updates)
        if not approved:
            return graph.get_state(config).values
        _drain(graph, None, config, on_event, start_seq)
        return graph.get_state(config).values

    if saver is not None:
        return run(build_graph(saver))
    with checkpointer() as cp:
        return run(build_graph(cp))

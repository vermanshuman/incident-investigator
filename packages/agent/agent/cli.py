"""Headless run: investigate "POST /checkout returning 500s since 14:02" """

import json
import os

import typer

from agent.graph import build_graph
from agent.guardrails import new_budget

cli = typer.Typer()


@cli.command()
def run(description: str, title: str = "CLI incident") -> None:
    graph = build_graph()
    state = {
        "run_id": "cli",
        "incident_title": title,
        "incident_description": description,
        "hypotheses": [],
        "evaluations": [],
        "tool_calls": [],
        "budget": new_budget(
            int(os.getenv("AGENT_MAX_STEPS", "25")),
            int(os.getenv("AGENT_MAX_TOKENS", "150000")),
            int(os.getenv("AGENT_MAX_SECONDS", "300")),
        ),
    }
    config = {"configurable": {"thread_id": "cli"}}
    for event in graph.stream(state, config, stream_mode="updates"):
        for node, update in event.items():
            typer.echo(f"[{node}] " + json.dumps(update, default=str)[:300])


if __name__ == "__main__":
    cli()

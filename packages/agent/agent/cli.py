"""Headless run:

    investigate "POST /checkout returning 500s since 14:02"
    investigate --title "Payments failing" "Every payment times out since 09:41 ..."
"""

import json
import os

import typer

from agent.llm import is_priced, model_name
from agent.runner import investigate

cli = typer.Typer(add_completion=False)


@cli.command()
def run(
    description: str,
    title: str = typer.Option("Incident", help="incident title"),
    show_json: bool = typer.Option(False, "--json", help="print the full report as JSON"),
    record: str = typer.Option("", help="save this run to a cassette file for free replay"),
    replay: str = typer.Option("", help="replay a recorded run: no API calls, no cost"),
    max_cost: float = typer.Option(0.0, help="hard cost cap in USD (default AGENT_MAX_COST_USD or 0.10)"),
) -> None:
    if record:
        os.environ["LLM_RECORD"] = record
    if replay:
        os.environ["LLM_REPLAY"] = replay
    if max_cost:
        os.environ["AGENT_MAX_COST_USD"] = str(max_cost)

    def on_event(ev: dict) -> None:
        tc = ev.get("tool_call")
        line = f"[{ev['seq']:2d}] {ev['node']:20s} {ev['note']}"
        typer.echo(line)
        if tc:
            typer.echo("     " + tc["summary"].replace("\n", "\n     ")[:1200])
        for h in ev.get("hypotheses", []):
            if h["status"] != "open":
                typer.secho(f"     {h['id']} -> {h['status'].upper()} ({h['confidence']:.1f}) {h['statement']}",
                            fg="green" if h["status"] == "confirmed" else "yellow")

    final = investigate(title, description, on_event)
    r = final.get("report")
    u = final.get("usage", {})
    typer.echo("")
    if r:
        typer.secho("ROOT CAUSE: " + r.root_cause, fg="cyan", bold=True)
        typer.echo(f"confidence={r.confidence.value} external={r.is_external}")
        typer.echo("evidence: " + ", ".join(c.source_ref for c in r.supporting_evidence))
        typer.echo("ruled out: " + " | ".join(r.ruled_out))
        typer.echo("fix: " + r.fix.summary)
        typer.echo("unchecked: " + "; ".join(r.unchecked_areas))
        if show_json:
            typer.echo(json.dumps(r.model_dump(), indent=2))
    cap = (final.get("budget") or {}).get("max_cost_usd") or 0.0
    mode = "  (replayed: no API calls)" if os.getenv("LLM_REPLAY") else ""
    if not os.getenv("LLM_REPLAY") and not is_priced(model_name(False)):
        mode = f"  (no price table for {model_name(False)}; token cap still applies)"
    typer.echo(f"\nstop: {final.get('stop_reason')} | steps={final.get('step')} llm_calls={u.get('calls')} "
               f"tokens_in={u.get('input_tokens')} tokens_out={u.get('output_tokens')} "
               f"cost=${u.get('cost_usd', 0):.4f} of ${cap:.2f} cap{mode}")
    if record:
        typer.secho(f'recorded to {record}  ->  replay free: python investigate.py --replay {record} "..."',
                    fg="cyan")


if __name__ == "__main__":
    cli()

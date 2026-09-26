"""Headless eval runner: for each case -> reset target -> inject fault -> run agent -> score.

    run-evals                 # all cases
    run-evals --only s01_null_check_v1
    run-evals --no-inject     # score against whatever state the target app is in

Requires the dev stack (python dev.py) to be running for injection.
"""

import json
import os
import subprocess
import sys
import time
from pathlib import Path

import typer
from rich.console import Console
from rich.table import Table

from agent.runner import investigate
from evals.cases import EvalCase, load_cases
from evals.scoring.score import score_run

cli = typer.Typer(add_completion=False)
console = Console()
ROOT = Path(__file__).resolve().parents[3]
RESULTS = ROOT / "docs" / "eval-results.json"


def _fault(*args: str) -> None:
    subprocess.run([sys.executable, str(ROOT / "fault.py"), *args], check=True, cwd=ROOT,
                   stdout=subprocess.DEVNULL)


def run_case(case: EvalCase, inject: bool, traffic_seconds: int) -> dict:
    if inject:
        _fault("reset", "--wipe")
        _fault("traffic", "--seconds", "8", "--concurrency", "4")
        _fault("apply", case.scenario, "--traffic-seconds", str(traffic_seconds))
    t0 = time.perf_counter()
    final = investigate(case.incident.title, case.incident.description)
    latency = time.perf_counter() - t0
    report = final.get("report")
    score = score_run(report, final.get("hypotheses", []), case.ground_truth) if report else None
    u = final.get("usage", {})
    return {
        "case": case.id, "scenario": case.scenario,
        "score": score.model_dump() if score else None,
        "root_cause": report.root_cause if report else None,
        "is_external": report.is_external if report else None,
        "stop_reason": final.get("stop_reason"),
        "steps": final.get("step"), "llm_calls": u.get("calls"),
        "tokens_in": u.get("input_tokens"), "tokens_out": u.get("output_tokens"),
        "cost_usd": u.get("cost_usd"), "latency_s": round(latency, 1),
    }


def _mark(score: dict | None, key: str) -> str:
    if not score:
        return "-"
    return "[green]ok[/]" if score.get(key) else "[red]x[/]"


@cli.command()
def run(only: str | None = None, inject: bool = True, traffic_seconds: int = 15) -> None:
    cases = [c for c in load_cases() if only is None or c.id == only]
    results = []
    for case in cases:
        console.print(f"[bold]{case.id}[/] ({case.scenario}) ...")
        results.append(run_case(case, inject, traffic_seconds))
    if inject:
        _fault("reset")

    table = Table("case", "score", "category", "culprit", "external", "cites", "steps", "calls", "tokens", "cost $", "s")
    for r in results:
        s = r["score"]
        table.add_row(r["case"], f"{s['total']:.2f}" if s else "-", _mark(s, "category_ok"), _mark(s, "culprit_ok"),
                      _mark(s, "external_ok"), _mark(s, "citations_ok"), str(r["steps"]), str(r["llm_calls"]),
                      str((r["tokens_in"] or 0) + (r["tokens_out"] or 0)), f"{r['cost_usd'] or 0:.3f}", str(r["latency_s"]))
    console.print(table)
    scored = [r["score"]["total"] for r in results if r["score"]]
    if scored:
        console.print(f"mean score {sum(scored) / len(scored):.2f} over {len(scored)} cases; "
                      f"total cost ${sum(r['cost_usd'] or 0 for r in results):.3f}")
    RESULTS.write_text(json.dumps({"model": os.getenv("LLM_MODEL", ""), "results": results}, indent=2))
    console.print(f"saved {RESULTS}")


if __name__ == "__main__":
    cli()

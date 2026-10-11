"""Headless eval runner: reset the target, inject one fault, investigate, score.

    run-evals                      # every case, live model
    run-evals --only s01_null_check_v1
    run-evals --repeat 3           # same cases 3x, to show run-to-run variance
    run-evals --replay             # score the recorded runs: free, deterministic
    run-evals --no-inject          # score against whatever state the app is in

`--replay` is what CI runs: it needs no API key and no target app, so a prompt
or graph change can be checked against recorded evidence for nothing.
"""

from __future__ import annotations

import json
import os
import statistics
import subprocess
import sys
import time
from datetime import UTC, datetime
from pathlib import Path

import typer
from rich.console import Console
from rich.table import Table

from agent.runner import investigate
from evals.cases import EvalCase, load_cases
from evals.scoring.score import Score, confirmed_category, score_run

cli = typer.Typer(add_completion=False)
console = Console()
ROOT = Path(__file__).resolve().parents[3]
RESULTS_JSON = ROOT / "docs" / "eval-results.json"
RESULTS_MD = ROOT / "docs" / "eval-results.md"
CASSETTES = ROOT / "cassettes"


def _fault(*args: str) -> None:
    subprocess.run([sys.executable, str(ROOT / "fault.py"), *args], check=True, cwd=ROOT,
                   stdout=subprocess.DEVNULL)


def cassette_for(scenario: str) -> Path:
    return CASSETTES / f"{scenario}.jsonl"


def run_case(case: EvalCase, inject: bool, traffic_seconds: int, replay: bool) -> dict:
    if replay:
        path = cassette_for(case.scenario)
        if not path.exists():
            return {"case": case.id, "scenario": case.scenario, "skipped":
                    f"no cassette at cassettes/{path.name}; record one first"}
        os.environ["LLM_REPLAY"] = str(path)
    else:
        os.environ.pop("LLM_REPLAY", None)
        if inject:
            _fault("reset", "--wipe")
            _fault("traffic", "--seconds", "8", "--concurrency", "4")
            _fault("apply", case.scenario, "--traffic-seconds", str(traffic_seconds))

    t0 = time.perf_counter()
    try:
        final = investigate(case.incident.title, case.incident.description)
        error = None
    except Exception as exc:  # noqa: BLE001 - a crashed run is a result, not a stop
        final, error = {}, f"{type(exc).__name__}: {exc}"[:200]
    latency = time.perf_counter() - t0

    report = final.get("report")
    hypotheses = final.get("hypotheses", [])
    score: Score | None = score_run(report, hypotheses, case.ground_truth) if report else None
    u = final.get("usage", {})
    return {
        "case": case.id, "scenario": case.scenario, "error": error,
        "score": score.model_dump() if score else None,
        "root_cause": report.root_cause if report else None,
        # What the agent actually said, so a miss can be read rather than guessed at.
        "agent_category": confirmed_category(hypotheses, report) if report else None,
        "expected_category": case.ground_truth.category,
        "expected_culprit": case.ground_truth.culprit,
        "is_external": report.is_external if report else None,
        "stop_reason": final.get("stop_reason"), "steps": final.get("step"),
        "llm_calls": u.get("calls"), "tokens": (u.get("input_tokens", 0) + u.get("output_tokens", 0)),
        "cost_usd": u.get("cost_usd", 0.0), "latency_s": round(latency, 1),
    }


def _mark(score: dict | None, key: str) -> str:
    if not score:
        return "[dim]-[/]"
    return "[green]ok[/]" if score.get(key) else "[red]x[/]"


def _summarise(results: list[dict]) -> dict:
    scored = [r for r in results if r.get("score")]
    totals = [r["score"]["total"] for r in scored]
    return {
        "cases": len(results),
        "scored": len(scored),
        "mean_score": round(statistics.mean(totals), 3) if totals else 0.0,
        "stdev_score": round(statistics.stdev(totals), 3) if len(totals) > 1 else 0.0,
        "root_cause_correct": sum(1 for r in scored if r["score"]["category_ok"]),
        "culprit_correct": sum(1 for r in scored if r["score"]["culprit_ok"]),
        "external_correct": sum(1 for r in scored if r["score"]["external_ok"]),
        "total_cost_usd": round(sum(r.get("cost_usd") or 0 for r in results), 4),
        "mean_llm_calls": round(statistics.mean([r["llm_calls"] for r in scored]), 1) if scored else 0,
        "mean_latency_s": (round(statistics.mean([r["latency_s"] for r in scored]), 1)
                           if scored else 0.0),
        "skipped": sum(1 for r in results if r.get("skipped")),
        "errored": sum(1 for r in results if r.get("error")),
    }


def _write_markdown(summary: dict, results: list[dict], model: str, replay: bool) -> None:
    lines = [
        "# Eval results",
        "",
        (
            f"_Generated {datetime.now(UTC).strftime('%Y-%m-%d %H:%M UTC')} · "
            f"model `{model or 'unknown'}`"
            f"{' · replayed from cassettes' if replay else ''}_"
        ),
        "",
        (
            f"**Mean score {summary['mean_score']:.2f}** over {summary['scored']} scored runs "
            f"(stdev {summary['stdev_score']:.2f}) · "
            f"root cause category right {summary['root_cause_correct']}/{summary['scored']} · "
            f"culprit right {summary['culprit_correct']}/{summary['scored']} · "
            f"external call right {summary['external_correct']}/{summary['scored']}"
        ),
        "",
        (
            f"Cost ${summary['total_cost_usd']:.4f} total · {summary['mean_llm_calls']} model "
            f"calls and {summary['mean_latency_s']}s per run on average."
        ),
        "",
        "| case | score | category | culprit | external | cites | steps | calls | tokens | $ | s |",
        "|---|---|---|---|---|---|---|---|---|---|---|",
    ]
    tick = {True: "ok", False: "**x**", None: "-"}
    for r in results:
        s = r.get("score")
        lines.append(
            f"| {r['case']} | {s['total']:.2f} | {tick[s['category_ok']]} | {tick[s['culprit_ok']]} | "
            f"{tick[s['external_ok']]} | {tick[s['citations_ok']]} | {r['steps']} | {r['llm_calls']} | "
            f"{r['tokens']} | {r['cost_usd']:.4f} | {r['latency_s']} |"
            if s else
            f"| {r['case']} | - | - | - | - | - | - | - | - | - | - |  <!-- {r.get('error') or r.get('skipped')} -->"
        )
    lines += [
        "",
        "## What each run concluded",
        "",
        "| case | expected | agent said | root cause |",
        "|---|---|---|---|",
        *[
            f"| {r['case']} | {r.get('expected_category')} | {r.get('agent_category') or '-'} | "
            f"{(r.get('root_cause') or '')[:140]} |"
            for r in results if r.get("score")
        ],
        "",
        "## What is scored",
        "",
        "- **category** - the confirmed hypothesis is in the right class of cause",
        ("- **culprit** - the report cites the file or config that actually caused it, which "
         "means it read the change rather than trusting the commit message"),
        "- **external** - the agent correctly said whether this was our bug",
        "- **cites** - the claims rest on evidence a tool really returned",
        "",
        "Failures are kept in the table on purpose: a suite that always passes is not measuring.",
    ]
    RESULTS_MD.write_text("\n".join(lines) + "\n", encoding="utf-8")


@cli.command()
def run(only: str | None = None, inject: bool = True, traffic_seconds: int = 15,
        repeat: int = 1, replay: bool = False) -> None:
    cases = [c for c in load_cases() if only is None or c.id == only]
    results: list[dict] = []
    for attempt in range(1, repeat + 1):
        for case in cases:
            label = f"{case.id}" + (f" (run {attempt})" if repeat > 1 else "")
            console.print(f"[bold]{label}[/] ...")
            row = run_case(case, inject and not replay, traffic_seconds, replay)
            row["attempt"] = attempt
            results.append(row)
    if inject and not replay:
        _fault("reset")

    table = Table("case", "score", "category", "culprit", "external", "cites",
                  "steps", "calls", "tokens", "$", "s")
    for r in results:
        s = r.get("score")
        table.add_row(
            r["case"], f"{s['total']:.2f}" if s else "[dim]-[/]",
            _mark(s, "category_ok"), _mark(s, "culprit_ok"), _mark(s, "external_ok"),
            _mark(s, "citations_ok"), str(r.get("steps", "-")), str(r.get("llm_calls", "-")),
            str(r.get("tokens", "-")), f"{r.get('cost_usd') or 0:.4f}", str(r.get("latency_s", "-")),
        )
    console.print(table)

    summary = _summarise(results)
    console.print(
        f"mean score [bold]{summary['mean_score']:.2f}[/] over {summary['scored']} runs "
        f"(stdev {summary['stdev_score']:.2f}) · total cost ${summary['total_cost_usd']:.4f}"
    )
    for r in results:
        if r.get("error") or r.get("skipped"):
            console.print(f"[yellow]{r['case']}: {r.get('error') or r.get('skipped')}[/]")

    model = os.getenv("LLM_MODEL", "")
    RESULTS_JSON.write_text(json.dumps(
        {"generated_at": datetime.now(UTC).isoformat(timespec="seconds"), "model": model,
         "replayed": replay, "summary": summary, "results": results}, indent=2), encoding="utf-8")
    _write_markdown(summary, results, model, replay)
    console.print(f"wrote {RESULTS_MD.relative_to(ROOT)} and {RESULTS_JSON.relative_to(ROOT)}")

    # Non-zero exit lets CI gate on a regression.
    if summary["scored"] and summary["mean_score"] < float(os.getenv("EVAL_MIN_SCORE", "0")):
        raise typer.Exit(1)


if __name__ == "__main__":
    cli()

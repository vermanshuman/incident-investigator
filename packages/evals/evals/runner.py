"""Headless eval runner.

For each case: reset target app -> inject fault -> run agent -> score -> record.
"""

import time

import typer
from rich.console import Console
from rich.table import Table

from evals.cases import load_cases

cli = typer.Typer()
console = Console()


@cli.command()
def run(only: str | None = None) -> None:
    cases = [c for c in load_cases() if only is None or c.id == only]
    table = Table("case", "category_ok", "culprit_ok", "external_ok", "steps", "latency_s")
    for case in cases:
        t0 = time.perf_counter()
        # TODO(phase 3): inject case.scenario, run graph, score_report(...)
        table.add_row(case.id, "-", "-", "-", "-", f"{time.perf_counter() - t0:.1f}")
    console.print(table)


if __name__ == "__main__":
    cli()

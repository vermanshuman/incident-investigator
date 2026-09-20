"""Fault injector CLI.

    inject-fault list
    inject-fault seed                     # create/refresh the target git repo
    inject-fault apply s01_null_check     # break the running service, then send traffic
    inject-fault reset                    # back to healthy main
    inject-fault traffic --seconds 30     # just send traffic

The service must be running under dev.py from the target repo: after a git
checkout the injector touches a restart flag and dev.py restarts the service,
which is what a deploy is.
"""

import os
import time
from datetime import UTC, datetime
from pathlib import Path

import httpx
import typer

from app.db import SessionLocal
from app.models import DeployEvent, RuntimeState
from faults import repo as repo_ops
from faults import traffic as traffic_gen
from faults.scenarios import SCENARIOS, is_implemented

cli = typer.Typer(help="Fault injector for the checkout service", no_args_is_help=True)

PROJECT_ROOT = Path(__file__).resolve().parents[3]
REPO = Path(os.getenv("TARGET_REPO_PATH", PROJECT_ROOT / "target-repo"))
APP_URL = os.getenv("TARGET_APP_URL", "http://localhost:8080")
DEPLOYER = ("Rahul Mehta", "rahul@example.com")
RESTART_FLAG = Path(os.getenv("TARGET_RESTART_FLAG", PROJECT_ROOT / "data" / "restart-target"))


def _request_restart() -> None:
    """Ask the supervisor (dev.py) to restart the service = deploy."""
    RESTART_FLAG.parent.mkdir(parents=True, exist_ok=True)
    RESTART_FLAG.touch()


def _set_runtime(values: dict[str, str]) -> None:
    with SessionLocal() as db:
        for k, v in values.items():
            row = db.get(RuntimeState, k)
            if row:
                row.value, row.updated_at = v, datetime.now(UTC)
            else:
                db.add(RuntimeState(key=k, value=v))
        db.commit()


def _deploy_event(kind: str, ref: str, summary: str, actor: str | None = DEPLOYER[0]) -> None:
    with SessionLocal() as db:
        db.add(DeployEvent(kind=kind, ref=ref, summary=summary, actor=actor))
        db.commit()


def _wait_for_version(sha: str | None, timeout: float = 30) -> bool:
    """Poll /health until the service reports the expected git version."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            v = httpx.get(f"{APP_URL}/health", timeout=2).json().get("version")
            if sha is None or (v and sha.startswith(v)):
                return True
        except httpx.HTTPError:
            pass
        time.sleep(0.5)
    return False


@cli.command("list")
def list_scenarios() -> None:
    for s in SCENARIOS.values():
        tag = "external" if s.is_external else ("ready" if is_implemented(s) else "todo")
        typer.echo(f"{s.id:22} {s.category:16} {tag:9} {s.title}")


@cli.command()
def seed(force: bool = typer.Option(False, help="recreate the repo even if it exists")) -> None:
    repo_ops.seed_repo(REPO, force=force)
    typer.echo(f"target repo ready at {REPO} ({repo_ops.git(REPO, 'rev-list', '--count', 'HEAD')} commits)")


@cli.command()
def apply(
    scenario_id: str,
    traffic_seconds: int = typer.Option(30, help="seconds of synthetic traffic after injecting"),
    no_traffic: bool = False,
) -> None:
    s = SCENARIOS.get(scenario_id)
    if s is None:
        raise typer.BadParameter(f"unknown scenario {scenario_id!r}; run `inject-fault list`")
    if not is_implemented(s):
        raise typer.BadParameter(f"{s.id} is not implemented yet")

    repo_ops.seed_repo(REPO)
    sha = None
    if s.patch:
        sha = repo_ops.commit_on_branch(REPO, f"fault/{s.id}", s.commit_message, DEPLOYER, s.patch)
        _deploy_event("deploy", sha[:12], s.commit_message)
        _request_restart()
        typer.echo(f"deploying {sha[:12]} on fault/{s.id}: {s.commit_message}")
        if not _wait_for_version(sha):
            typer.secho("warning: service did not come up with the new version; "
                        "is it running under dev.py?", fg="yellow")
    if s.runtime:
        _set_runtime(s.runtime)
        typer.echo(f"runtime state changed: {s.runtime} (no deploy, no commit)")

    typer.secho(f"fault active: {s.id} - {s.title}", fg="red")
    if not no_traffic:
        traffic(traffic_seconds, s.traffic_concurrency)


@cli.command()
def reset(wipe: bool = typer.Option(False, help="also delete logs, metrics and deploy events")) -> None:
    if REPO.exists():
        before = repo_ops.git(REPO, "rev-parse", "--abbrev-ref", "HEAD")
        repo_ops.checkout_main(REPO)
        if before != "main":
            sha = repo_ops.git(REPO, "rev-parse", "HEAD")
            _deploy_event("deploy", sha[:12], f"Rollback: redeploy main (was {before})")
            _request_restart()
            _wait_for_version(sha)
    _set_runtime({"payment_provider_status": "up",
                  "payment_provider_expected_api_key": "pk_live_7f3a9c2e"})
    if wipe:
        from sqlalchemy import delete

        from app.models import AppLog, MetricSample
        from app.models import DeployEvent as DE

        with SessionLocal() as db:
            for t in (AppLog, MetricSample, DE):
                db.execute(delete(t))
            db.commit()
    typer.secho("target app reset to healthy main", fg="green")


@cli.command()
def traffic(seconds: int = 30, concurrency: int = 6, seed: int | None = None) -> None:
    typer.echo(f"sending traffic for {seconds}s with {concurrency} workers ...")
    stats = traffic_gen.run(APP_URL, seconds, concurrency, seed)
    for k, v in sorted(stats.items()):
        typer.echo(f"  {v:5d}  {k}")


if __name__ == "__main__":
    cli()

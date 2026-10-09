"""Execute an investigation off the request path and stream its events.

The agent's graph is synchronous, so it runs in a worker thread; each event it
emits is persisted to run_events (so a page refresh can replay the run) and
published to the bus (so open browsers see it immediately).

In Phase 6 this becomes a separate worker process consuming a Redis queue. The
seam is `start_run`: the router only ever enqueues, never executes inline.
"""

from __future__ import annotations

import asyncio
import os
from datetime import UTC, datetime

from agent.runner import investigate, resume
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.core.db import SessionLocal
from app.core.events import bus, run_channel
from app.models import (
    AuditEvent,
    Hypothesis,
    HypothesisStatus,
    Incident,
    IncidentStatus,
    Report,
    Run,
    RunEvent,
    RunStatus,
)


def _persist_event(db: Session, run: Run, seq: int, event: dict) -> None:
    kind = "tool_call" if event.get("tool_call") else ("report" if event.get("report") else "node")
    db.add(RunEvent(run_id=run.id, seq=seq, type=kind, payload=event))


def _sync_hypotheses(db: Session, run_id: str, rows: list[dict]) -> None:
    existing = {h.statement: h for h in db.query(Hypothesis).filter(Hypothesis.run_id == run_id)}
    for row in rows:
        h = existing.get(row["statement"])
        if h is None:
            h = Hypothesis(run_id=run_id, statement=row["statement"], category=row["category"])
            db.add(h)
        h.status = HypothesisStatus(row["status"])
        h.confidence = row["confidence"]
        h.evidence_for = row.get("evidence_for", [])
        h.evidence_against = row.get("evidence_against", [])


def _save_report(db: Session, run_id: str, report: dict) -> None:
    row = db.query(Report).filter(Report.run_id == run_id).one_or_none() or Report(run_id=run_id)
    row.root_cause = report["root_cause"]
    row.confidence = report["confidence"]
    row.fix_proposal = report["fix"]["summary"]
    row.unchecked_areas = report["unchecked_areas"]
    row.body_markdown = _markdown(report)
    db.add(row)


def _markdown(r: dict) -> str:
    """The report as it will be posted to GitHub after approval (Phase 5)."""
    cites = "\n".join(f"- `{c['source_ref']}` ({c['tool']}): {c['excerpt']}" for c in r["supporting_evidence"])
    return "\n".join([
        f"## Summary\n{r['summary']}",
        f"\n## Customer impact\n{r['customer_impact']}",
        "\n## Timeline\n" + "\n".join(f"- {t}" for t in r["timeline"]),
        f"\n## Root cause\n{r['root_cause']}\n\nConfidence: **{r['confidence']}**"
        + ("  ·  cause is external to our code" if r["is_external"] else ""),
        f"\n## Evidence\n{cites}" if cites else "",
        "\n## Ruled out\n" + "\n".join(f"- {x}" for x in r["ruled_out"]),
        f"\n## Proposed fix\n{r['fix']['summary']}\n\n```\n{r['fix']['change']}\n```\n"
        + f"Rollback: {r['fix']['rollback']}",
        "\n## Not checked\n" + "\n".join(f"- {x}" for x in r["unchecked_areas"]),
    ])


def _blocking_investigate(run_id: str, org_id: str, title: str, description: str,
                          loop: asyncio.AbstractEventLoop, replay: str | None) -> None:
    """Runs in a worker thread. Owns its own DB session."""
    channel = run_channel(org_id, run_id)
    if replay:
        os.environ["LLM_REPLAY"] = replay
    seq = 0

    def on_event(event: dict) -> None:
        nonlocal seq
        seq = event["seq"]
        with SessionLocal() as db:
            run = db.get(Run, run_id)
            _persist_event(db, run, seq, event)
            if event.get("hypotheses"):
                _sync_hypotheses(db, run_id, event["hypotheses"])
            if event.get("usage"):
                u = event["usage"]
                run.llm_calls, run.cost_usd = u["calls"], u["cost_usd"]
                run.token_count = u["input_tokens"] + u["output_tokens"]
            if event.get("report"):
                _save_report(db, run_id, event["report"])
            db.commit()
        bus.publish_threadsafe(loop, channel, event)

    try:
        final = investigate(title, description, on_event=on_event, thread_id=run_id)
        status, error = RunStatus.awaiting_approval, None
    except Exception as exc:  # noqa: BLE001 - a failed run must be visible, not silent
        final, status, error = {}, RunStatus.failed, f"{type(exc).__name__}: {exc}"[:500]

    with SessionLocal() as db:
        run = db.get(Run, run_id)
        run.status = status
        run.error = error
        run.finished_at = datetime.now(UTC)
        run.step_count = final.get("step", run.step_count)
        run.stop_reason = final.get("stop_reason")
        run.replayed = bool(replay)
        incident = db.get(Incident, run.incident_id)
        incident.status = IncidentStatus.awaiting_approval if error is None else IncidentStatus.open
        db.commit()
    bus.publish_threadsafe(loop, channel, {
        "seq": seq + 1, "node": "finished", "note": error or "Awaiting approval",
        "status": status.value, "stop_reason": final.get("stop_reason"), "error": error,
    })
    asyncio.run_coroutine_threadsafe(bus.close(channel), loop)


async def start_run(run: Run, incident: Incident, replay: str | None = None) -> None:
    """Enqueue the run. Phase 6 replaces the thread with a Redis consumer."""
    loop = asyncio.get_running_loop()
    with SessionLocal() as db:
        row = db.get(Run, run.id)
        row.status = RunStatus.running
        row.started_at = datetime.now(UTC)
        db.commit()
    asyncio.create_task(asyncio.to_thread(
        _blocking_investigate, run.id, run.org_id, incident.title, incident.description, loop, replay
    ))


def _event_recorder(run_id: str, org_id: str, loop: asyncio.AbstractEventLoop, start_seq: int):
    """Persist and publish each event of a resumed run, continuing the sequence."""
    channel = run_channel(org_id, run_id)
    state = {"seq": start_seq}

    def on_event(event: dict) -> None:
        state["seq"] = event["seq"]
        with SessionLocal() as db:
            _persist_event(db, db.get(Run, run_id), event["seq"], event)
            db.commit()
        bus.publish_threadsafe(loop, channel, event)

    return on_event, state


def _decide(run_id: str, org_id: str, approved: bool, actor: str, overrides: dict | None,
            loop: asyncio.AbstractEventLoop, start_seq: int) -> None:
    """Runs in a worker thread: resume the paused graph and record the outcome."""
    channel = run_channel(org_id, run_id)
    on_event, seq_state = _event_recorder(run_id, org_id, loop, start_seq)
    issue_url, error = None, None
    try:
        final = resume(run_id, approved=approved, report_overrides=overrides,
                       on_event=on_event, start_seq=start_seq)
        issue_url = final.get("github_issue_url")
    except Exception as exc:  # noqa: BLE001 - a failed decision must be visible
        error = f"{type(exc).__name__}: {exc}"[:500]

    with SessionLocal() as db:
        run = db.get(Run, run_id)
        run.status = RunStatus.failed if error else (
            RunStatus.completed if approved else RunStatus.rejected
        )
        run.error = error or run.error
        run.finished_at = datetime.now(UTC)
        report = db.query(Report).filter(Report.run_id == run_id).one_or_none()
        if report is not None:
            report.approved_by = actor
            report.approved_at = datetime.now(UTC)
            report.github_issue_url = issue_url
        incident = db.get(Incident, run.incident_id)
        incident.status = IncidentStatus.resolved if approved and not error else IncidentStatus.open
        if issue_url:
            db.add(AuditEvent(org_id=org_id, run_id=run_id, actor=actor,
                              action="issue_created", detail={"url": issue_url}))
        db.commit()

    bus.publish_threadsafe(loop, channel, {
        "seq": seq_state["seq"] + 1, "node": "finished",
        "note": error or (f"Issue created: {issue_url}" if issue_url else
                          ("Approved" if approved else "Rejected")),
        "status": (RunStatus.failed if error else
                   (RunStatus.completed if approved else RunStatus.rejected)).value,
        "github_issue_url": issue_url, "error": error,
    })
    asyncio.run_coroutine_threadsafe(bus.close(channel), loop)


async def decide_run(run: Run, approved: bool, actor: str, overrides: dict | None = None) -> None:
    """Approve or reject a paused run, off the request path."""
    loop = asyncio.get_running_loop()
    with SessionLocal() as db:
        row = db.get(Run, run.id)
        row.status = RunStatus.running
        last_seq = db.query(func.max(RunEvent.seq)).filter(RunEvent.run_id == run.id).scalar() or 0
        db.add(AuditEvent(org_id=run.org_id, run_id=run.id, actor=actor,
                          action="approved" if approved else "rejected",
                          detail={"edited_fields": sorted(overrides or {})}))
        db.commit()
    asyncio.create_task(asyncio.to_thread(
        _decide, run.id, run.org_id, approved, actor, overrides, loop, last_seq
    ))

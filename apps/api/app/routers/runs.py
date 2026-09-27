import asyncio
import json
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session
from sse_starlette.sse import EventSourceResponse

from app.core.db import get_db
from app.core.events import bus, run_channel
from app.core.tenancy import current_org
from app.models import Hypothesis, Organization, Report, Run, RunEvent, RunStatus
from app.routers.incidents import RunOut

router = APIRouter(prefix="/runs", tags=["runs"])

# How long the stream waits before sending a keep-alive comment, so proxies
# and browsers do not treat an idle-but-live run as a dropped connection.
HEARTBEAT_SECONDS = 15


class HypothesisOut(BaseModel):
    id: str
    statement: str
    category: str
    status: str
    confidence: float
    evidence_for: list[dict]
    evidence_against: list[dict]

    model_config = {"from_attributes": True}


class ReportOut(BaseModel):
    root_cause: str
    confidence: str
    fix_proposal: str
    unchecked_areas: list[str]
    body_markdown: str
    approved_by: str | None
    github_issue_url: str | None

    model_config = {"from_attributes": True}


class RunDetail(RunOut):
    events: list[dict]
    hypotheses: list[HypothesisOut]
    report: ReportOut | None


def _scoped(db: Session, org: Organization, run_id: str) -> Run:
    run = db.get(Run, run_id)
    if run is None or run.org_id != org.id:
        raise HTTPException(404, "run not found")
    return run


def _events(db: Session, run_id: str, after: int = 0) -> list[dict]:
    rows = db.scalars(
        select(RunEvent).where(RunEvent.run_id == run_id, RunEvent.seq > after).order_by(RunEvent.seq)
    )
    return [{"seq": e.seq, "type": e.type, "ts": e.ts.isoformat(), **e.payload} for e in rows]


@router.get("", response_model=list[RunOut])
def list_runs(db: Session = Depends(get_db), org: Organization = Depends(current_org)) -> list[Run]:
    return list(db.scalars(
        select(Run).where(Run.org_id == org.id).order_by(Run.started_at.desc()).limit(50)
    ))


@router.get("/{run_id}", response_model=RunDetail)
def get_run(run_id: str, db: Session = Depends(get_db),
            org: Organization = Depends(current_org)) -> RunDetail:
    run = _scoped(db, org, run_id)
    hyps = db.scalars(select(Hypothesis).where(Hypothesis.run_id == run_id))
    report = db.scalar(select(Report).where(Report.run_id == run_id))
    return RunDetail(
        **RunOut.model_validate(run).model_dump(),
        events=_events(db, run_id),
        hypotheses=[HypothesisOut.model_validate(h) for h in hyps],
        report=ReportOut.model_validate(report) if report else None,
    )


@router.get("/{run_id}/stream")
async def stream_events(run_id: str, request: Request, last_seq: int = 0,
                        db: Session = Depends(get_db),
                        org: Organization = Depends(current_org)):
    """Server-Sent Events for a run.

    Replays stored events the client has not seen (so a refresh or reconnect
    loses nothing), then follows the live bus until the run finishes.
    """
    run = _scoped(db, org, run_id)
    channel = run_channel(org.id, run_id)
    backlog = _events(db, run_id, after=last_seq)
    # A run paused at the approval gate emits nothing further until a human
    # acts, so the stream ends rather than holding the connection open.
    terminal = run.status in {RunStatus.completed, RunStatus.failed,
                              RunStatus.rejected, RunStatus.awaiting_approval}

    async def generator():
        seen = last_seq
        for event in backlog:
            seen = max(seen, event["seq"])
            yield {"event": "run", "data": json.dumps(event)}
        if terminal:
            yield {"event": "end", "data": json.dumps({"status": run.status.value})}
            return

        async with bus.subscribe(channel) as queue:
            while not await request.is_disconnected():
                try:
                    event: dict[str, Any] | None = await asyncio.wait_for(
                        queue.get(), timeout=HEARTBEAT_SECONDS
                    )
                except TimeoutError:
                    yield {"event": "ping", "data": ""}
                    continue
                if event is None:  # run finished
                    yield {"event": "end", "data": json.dumps({"status": "finished"})}
                    return
                if event.get("seq", 0) <= seen:
                    continue  # already delivered from the backlog
                seen = event["seq"]
                yield {"event": "run", "data": json.dumps(event, default=str)}

    return EventSourceResponse(generator())

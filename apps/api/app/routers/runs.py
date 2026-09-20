import asyncio
import json

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session
from sse_starlette.sse import EventSourceResponse

from app.core.db import get_db
from app.models import Run
from app.routers.incidents import RunOut

router = APIRouter(prefix="/runs", tags=["runs"])


@router.get("/{run_id}", response_model=RunOut)
def get_run(run_id: str, db: Session = Depends(get_db)) -> Run:
    run = db.get(Run, run_id)
    if run is None:
        raise HTTPException(404, "run not found")
    return run


@router.get("/{run_id}/events")
def list_events(run_id: str, db: Session = Depends(get_db)) -> list[dict]:
    run = db.get(Run, run_id)
    if run is None:
        raise HTTPException(404, "run not found")
    return [
        {"seq": e.seq, "type": e.type, "payload": e.payload, "ts": e.ts.isoformat()}
        for e in run.events
    ]


@router.get("/{run_id}/stream")
async def stream_events(run_id: str, request: Request):
    """Server-Sent Events stream of run events.

    Phase 0: replays stored events then closes.
    Phase 4: subscribe to Redis pub/sub channel `run:{run_id}` and relay live.
    """

    async def generator():
        yield {"event": "connected", "data": json.dumps({"run_id": run_id})}
        # TODO(phase 4): replace with Redis subscription
        while not await request.is_disconnected():
            await asyncio.sleep(15)
            yield {"event": "ping", "data": ""}

    return EventSourceResponse(generator())

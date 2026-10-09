from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.auth import Principal, requires
from app.core.db import get_db
from app.core.plans import LimitReached, check_can_start_run
from app.core.tenancy import current_org
from app.models import Incident, IncidentStatus, Organization, Role, Run, RunStatus, Severity
from app.services import runs as run_service

router = APIRouter(prefix="/incidents", tags=["incidents"])


class IncidentCreate(BaseModel):
    title: str = Field(max_length=200)
    description: str
    severity: Severity = Severity.high
    source: str = "manual"


class IncidentOut(BaseModel):
    id: str
    title: str
    description: str
    severity: Severity
    status: IncidentStatus
    source: str
    created_at: datetime
    latest_run_id: str | None = None

    model_config = {"from_attributes": True}


class RunOut(BaseModel):
    id: str
    incident_id: str
    status: RunStatus
    thread_id: str
    started_at: datetime | None
    finished_at: datetime | None
    step_count: int
    token_count: int
    llm_calls: int
    cost_usd: float
    stop_reason: str | None
    error: str | None
    replayed: bool

    model_config = {"from_attributes": True}


class InvestigateRequest(BaseModel):
    replay: str | None = Field(
        default=None,
        description="cassette name to replay instead of calling an LLM, e.g. s01_null_check",
    )


def _out(incident: Incident) -> IncidentOut:
    latest = max(incident.runs, key=lambda r: r.started_at or r.id, default=None)
    return IncidentOut.model_validate(incident).model_copy(
        update={"latest_run_id": latest.id if latest else None}
    )


@router.get("", response_model=list[IncidentOut])
def list_incidents(db: Session = Depends(get_db), org: Organization = Depends(current_org),
                   _: Principal = Depends(requires(Role.viewer))) -> list[IncidentOut]:
    rows = db.scalars(
        select(Incident).where(Incident.org_id == org.id).order_by(Incident.created_at.desc())
    )
    return [_out(i) for i in rows]


@router.post("", response_model=IncidentOut, status_code=201)
def create_incident(body: IncidentCreate, db: Session = Depends(get_db),
                    org: Organization = Depends(current_org),
                    _: Principal = Depends(requires(Role.approver))) -> IncidentOut:
    incident = Incident(org_id=org.id, **body.model_dump())
    db.add(incident)
    db.commit()
    return _out(incident)


def _get_scoped(db: Session, org: Organization, incident_id: str) -> Incident:
    incident = db.get(Incident, incident_id)
    if incident is None or incident.org_id != org.id:
        raise HTTPException(404, "incident not found")
    return incident


@router.get("/{incident_id}", response_model=IncidentOut)
def get_incident(incident_id: str, db: Session = Depends(get_db),
                 org: Organization = Depends(current_org),
                 _: Principal = Depends(requires(Role.viewer))) -> IncidentOut:
    return _out(_get_scoped(db, org, incident_id))


@router.post("/{incident_id}/investigate", response_model=RunOut, status_code=202)
async def investigate(incident_id: str, body: InvestigateRequest | None = None,
                      db: Session = Depends(get_db),
                      org: Organization = Depends(current_org),
                      _: Principal = Depends(requires(Role.approver))) -> Run:
    """Create a run and start it off the request path. Returns immediately so
    the UI can subscribe to the event stream while the agent works."""
    incident = _get_scoped(db, org, incident_id)
    replay = body.replay if body else None
    try:
        # A replay spends nothing, so it is never blocked by a plan limit.
        check_can_start_run(db, org, replayed=bool(replay))
    except LimitReached as exc:
        raise HTTPException(402, str(exc)) from exc
    run = Run(org_id=org.id, incident_id=incident.id, replayed=bool(replay))
    incident.status = IncidentStatus.investigating
    db.add(run)
    db.commit()
    db.refresh(run)
    await run_service.start_run(run, incident, replay=replay)
    return run

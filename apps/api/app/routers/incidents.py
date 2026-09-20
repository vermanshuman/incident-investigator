from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.models import Incident, IncidentStatus, Run, RunStatus, Severity

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
    cost_usd: float

    model_config = {"from_attributes": True}


@router.get("", response_model=list[IncidentOut])
def list_incidents(db: Session = Depends(get_db)) -> list[Incident]:
    return list(db.scalars(select(Incident).order_by(Incident.created_at.desc())))


@router.post("", response_model=IncidentOut, status_code=201)
def create_incident(body: IncidentCreate, db: Session = Depends(get_db)) -> Incident:
    incident = Incident(**body.model_dump())
    db.add(incident)
    db.commit()
    return incident


@router.get("/{incident_id}", response_model=IncidentOut)
def get_incident(incident_id: str, db: Session = Depends(get_db)) -> Incident:
    incident = db.get(Incident, incident_id)
    if incident is None:
        raise HTTPException(404, "incident not found")
    return incident


@router.post("/{incident_id}/investigate", response_model=RunOut, status_code=202)
def investigate(incident_id: str, db: Session = Depends(get_db)) -> Run:
    """Create a run and enqueue it. The worker picks it up (Phase 4)."""
    incident = db.get(Incident, incident_id)
    if incident is None:
        raise HTTPException(404, "incident not found")
    run = Run(incident_id=incident.id)
    incident.status = IncidentStatus.investigating
    db.add(run)
    db.commit()
    # TODO(phase 4): publish run.id to the Redis queue
    return run

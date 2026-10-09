"""Dashboard numbers: what an operator (and later, a plan limit) cares about."""

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.auth import Principal, requires
from app.core.db import get_db
from app.core.tenancy import current_org
from app.models import Incident, IncidentStatus, Organization, Role, Run, RunStatus

router = APIRouter(prefix="/dashboard", tags=["dashboard"])


class Usage(BaseModel):
    runs: int
    run_limit: int
    cost_usd: float
    cost_limit_usd: float
    tokens: int


class Stats(BaseModel):
    org: str
    plan: str
    open_incidents: int
    runs_awaiting_approval: int
    completed_runs: int
    failed_runs: int
    avg_seconds_to_root_cause: float | None
    avg_cost_usd: float | None
    usage: Usage


@router.get("", response_model=Stats)
def stats(db: Session = Depends(get_db), org: Organization = Depends(current_org),
          _: Principal = Depends(requires(Role.viewer))) -> Stats:
    def count(*where) -> int:
        return db.scalar(select(func.count()).select_from(Run).where(Run.org_id == org.id, *where)) or 0

    finished = list(db.scalars(
        select(Run).where(Run.org_id == org.id, Run.finished_at.is_not(None), Run.started_at.is_not(None))
    ))
    durations = [(r.finished_at - r.started_at).total_seconds() for r in finished]
    costs = [r.cost_usd for r in finished if r.cost_usd]
    total_cost = db.scalar(select(func.sum(Run.cost_usd)).where(Run.org_id == org.id)) or 0.0
    total_tokens = db.scalar(select(func.sum(Run.token_count)).where(Run.org_id == org.id)) or 0

    return Stats(
        org=org.name,
        plan=org.plan,
        open_incidents=db.scalar(select(func.count()).select_from(Incident).where(
            Incident.org_id == org.id, Incident.status != IncidentStatus.closed)) or 0,
        runs_awaiting_approval=count(Run.status == RunStatus.awaiting_approval),
        completed_runs=count(Run.status == RunStatus.completed),
        failed_runs=count(Run.status == RunStatus.failed),
        avg_seconds_to_root_cause=round(sum(durations) / len(durations), 1) if durations else None,
        avg_cost_usd=round(sum(costs) / len(costs), 4) if costs else None,
        usage=Usage(
            runs=count(), run_limit=org.monthly_run_limit,
            cost_usd=round(float(total_cost), 4), cost_limit_usd=org.monthly_cost_limit_usd,
            tokens=int(total_tokens),
        ),
    )

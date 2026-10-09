"""Machine entry points: alert webhooks in, Stripe webhooks in.

An alerting system (PagerDuty, Grafana, a cron) opens an incident with an org
API key and may ask for the investigation to start immediately - which is the
whole point of an agent that works while nobody is watching.
"""

from fastapi import APIRouter, Depends, Header, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.core import billing
from app.core.auth import Principal, current_principal
from app.core.db import get_db
from app.core.plans import PLANS, LimitReached, apply_plan, check_can_start_run
from app.models import AuditEvent, Incident, IncidentStatus, Organization, Run, Severity
from app.routers.incidents import IncidentOut, RunOut, _out
from app.services import runs as run_service

router = APIRouter(prefix="/v1", tags=["ingest"])


class AlertIn(BaseModel):
    title: str = Field(max_length=200)
    description: str
    severity: Severity = Severity.high
    source: str = Field(default="alert", max_length=20)
    investigate: bool = Field(default=True, description="start an investigation immediately")


class AlertAccepted(BaseModel):
    incident: IncidentOut
    run: RunOut | None
    note: str


@router.post("/incidents", response_model=AlertAccepted, status_code=202)
async def ingest_incident(body: AlertIn, db: Session = Depends(get_db),
                          principal: Principal = Depends(current_principal)) -> AlertAccepted:
    """Open an incident from an alert, optionally investigating it at once."""
    org = principal.org
    incident = Incident(org_id=org.id, title=body.title, description=body.description,
                        severity=body.severity, source=body.source)
    db.add(incident)
    db.commit()

    run, note = None, "Incident recorded."
    if body.investigate:
        try:
            check_can_start_run(db, org)
        except LimitReached as exc:
            # The incident is still recorded: losing an alert because billing
            # ran out would be worse than not investigating it.
            return AlertAccepted(incident=_out(incident), run=None, note=str(exc))
        run = Run(org_id=org.id, incident_id=incident.id)
        incident.status = IncidentStatus.investigating
        db.add(run)
        db.commit()
        db.refresh(run)
        await run_service.start_run(run, incident)
        note = "Investigation started."

    db.add(AuditEvent(org_id=org.id, run_id=run.id if run else None, actor=principal.actor,
                      action="incident_ingested", detail={"source": body.source}))
    db.commit()
    return AlertAccepted(incident=_out(incident), run=run, note=note)


@router.post("/stripe/webhook", status_code=200)
async def stripe_webhook(request: Request, db: Session = Depends(get_db),
                         stripe_signature: str | None = Header(default=None)) -> dict:
    """Apply a plan once Stripe confirms the payment."""
    payload = await request.body()
    try:
        event = billing.verify_webhook(payload, stripe_signature)
    except ValueError as exc:
        raise HTTPException(400, f"invalid webhook: {exc}") from exc

    if event.get("type") != "checkout.session.completed":
        return {"ignored": event.get("type")}

    session = event["data"]["object"]
    metadata = session.get("metadata") or {}
    org = db.get(Organization, metadata.get("org_id") or session.get("client_reference_id"))
    plan = PLANS.get(metadata.get("plan", ""))
    if org is None or plan is None:
        raise HTTPException(404, "unknown organization or plan in webhook metadata")

    apply_plan(org, plan)
    org.stripe_customer_id = session.get("customer") or org.stripe_customer_id
    org.stripe_subscription_id = session.get("subscription") or org.stripe_subscription_id
    db.add(AuditEvent(org_id=org.id, actor="stripe", action="plan_changed",
                      detail={"plan": plan.key, "simulated": False}))
    db.commit()
    return {"applied": plan.key, "org": org.id}


@router.get("/ping")
def ping(principal: Principal = Depends(current_principal)) -> dict:
    """Lets an integration check its key without creating anything."""
    return {"ok": True, "org": principal.org.name, "actor": principal.actor,
            "role": principal.role.value}



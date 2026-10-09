"""Organization settings: members, API keys, plan and usage."""

from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.auth import Principal, current_principal, mint_api_key, requires
from app.core.billing import CheckoutResult, start_checkout
from app.core.db import get_db
from app.core.plans import PLANS, apply_plan, plan_for, usage_for
from app.core.tenancy import add_member, current_org
from app.models import ApiKey, AuditEvent, Membership, Organization, Role, User

router = APIRouter(prefix="/org", tags=["organization"])


class PlanOut(BaseModel):
    key: str
    name: str
    price_usd_month: int
    monthly_run_limit: int
    monthly_cost_limit_usd: float
    seats: int
    blurb: str
    current: bool


class UsageOut(BaseModel):
    runs: int
    run_limit: int
    runs_left: int
    cost_usd: float
    cost_limit_usd: float
    tokens: int
    period_start: datetime
    over_run_limit: bool
    over_cost_limit: bool


class MemberOut(BaseModel):
    user_id: str
    name: str
    email: str | None
    role: Role
    joined: datetime


class ApiKeyOut(BaseModel):
    id: str
    name: str
    prefix: str
    created_by: str | None
    created_at: datetime
    last_used_at: datetime | None
    revoked: bool


class OrgOut(BaseModel):
    id: str
    name: str
    slug: str
    plan: str
    your_role: Role
    usage: UsageOut
    plans: list[PlanOut]
    seats_used: int
    seat_limit: int


def _usage_out(db: Session, org: Organization) -> UsageOut:
    u = usage_for(db, org)
    return UsageOut(
        runs=u.runs, run_limit=u.run_limit, runs_left=u.runs_left, cost_usd=u.cost_usd,
        cost_limit_usd=u.cost_limit_usd, tokens=u.tokens, period_start=u.period_start,
        over_run_limit=u.over_run_limit, over_cost_limit=u.over_cost_limit,
    )


@router.get("", response_model=OrgOut)
def get_org(db: Session = Depends(get_db), principal: Principal = Depends(current_principal),
            org: Organization = Depends(current_org)) -> OrgOut:
    seats = db.query(Membership).filter(Membership.org_id == org.id).count()
    return OrgOut(
        id=org.id, name=org.name, slug=org.slug, plan=org.plan, your_role=principal.role,
        usage=_usage_out(db, org), seats_used=seats, seat_limit=plan_for(org).seats,
        plans=[PlanOut(**{**p.__dict__, "current": p.key == org.plan}) for p in PLANS.values()],
    )


# --- members ----------------------------------------------------------

@router.get("/members", response_model=list[MemberOut])
def list_members(db: Session = Depends(get_db), org: Organization = Depends(current_org),
                 _: Principal = Depends(requires(Role.viewer))) -> list[MemberOut]:
    rows = db.scalars(select(Membership).where(Membership.org_id == org.id))
    return [MemberOut(user_id=m.user_id, name=m.user.name, email=m.user.email,
                      role=m.role, joined=m.created_at) for m in rows]


class InviteMember(BaseModel):
    name: str = Field(max_length=120)
    email: str | None = None
    role: Role = Role.approver


@router.post("/members", response_model=MemberOut, status_code=201)
def invite_member(body: InviteMember, db: Session = Depends(get_db),
                  org: Organization = Depends(current_org),
                  principal: Principal = Depends(requires(Role.owner))) -> MemberOut:
    """Add someone to this organization. Seats are a plan limit."""
    seats = db.query(Membership).filter(Membership.org_id == org.id).count()
    limit = plan_for(org).seats
    if seats >= limit:
        raise HTTPException(402, f"the {org.plan} plan includes {limit} seats; upgrade to add more")

    user = db.scalar(select(User).where(User.email == body.email)) if body.email else None
    if user is None:
        user = User(name=body.name.strip(), email=body.email)
        db.add(user)
        db.commit()
    membership = add_member(db, org, user, body.role)
    db.add(AuditEvent(org_id=org.id, actor=principal.actor, action="member_added",
                      detail={"user": user.name, "role": body.role.value}))
    db.commit()
    return MemberOut(user_id=user.id, name=user.name, email=user.email,
                     role=membership.role, joined=membership.created_at)


class ChangeRole(BaseModel):
    role: Role


@router.put("/members/{user_id}", response_model=MemberOut)
def change_role(user_id: str, body: ChangeRole, db: Session = Depends(get_db),
                org: Organization = Depends(current_org),
                principal: Principal = Depends(requires(Role.owner))) -> MemberOut:
    membership = db.scalar(select(Membership).where(
        Membership.org_id == org.id, Membership.user_id == user_id))
    if membership is None:
        raise HTTPException(404, "not a member of this organization")
    if membership.role == Role.owner and body.role != Role.owner:
        owners = db.query(Membership).filter(
            Membership.org_id == org.id, Membership.role == Role.owner).count()
        if owners <= 1:
            raise HTTPException(409, "an organization must keep at least one owner")
    membership.role = body.role
    db.add(AuditEvent(org_id=org.id, actor=principal.actor, action="role_changed",
                      detail={"user": membership.user.name, "role": body.role.value}))
    db.commit()
    return MemberOut(user_id=user_id, name=membership.user.name, email=membership.user.email,
                     role=membership.role, joined=membership.created_at)


# --- API keys ---------------------------------------------------------

def _key_out(key: ApiKey) -> ApiKeyOut:
    return ApiKeyOut(id=key.id, name=key.name, prefix=key.prefix, created_by=key.created_by,
                     created_at=key.created_at, last_used_at=key.last_used_at,
                     revoked=key.revoked_at is not None)


@router.get("/api-keys", response_model=list[ApiKeyOut])
def list_keys(db: Session = Depends(get_db), org: Organization = Depends(current_org),
              _: Principal = Depends(requires(Role.admin))) -> list[ApiKeyOut]:
    rows = db.scalars(select(ApiKey).where(ApiKey.org_id == org.id).order_by(ApiKey.created_at))
    return [_key_out(k) for k in rows]


class NewKey(BaseModel):
    name: str = Field(max_length=80, description="what will use this key, e.g. 'Grafana alerts'")


class NewKeyOut(ApiKeyOut):
    secret: str = Field(description="shown once; it cannot be recovered")


@router.post("/api-keys", response_model=NewKeyOut, status_code=201)
def create_key(body: NewKey, db: Session = Depends(get_db),
               org: Organization = Depends(current_org),
               principal: Principal = Depends(requires(Role.admin))) -> NewKeyOut:
    key, secret = mint_api_key(db, org, body.name.strip(), principal.actor)
    db.add(AuditEvent(org_id=org.id, actor=principal.actor, action="api_key_created",
                      detail={"name": key.name, "prefix": key.prefix}))
    db.commit()
    return NewKeyOut(**_key_out(key).model_dump(), secret=secret)


@router.delete("/api-keys/{key_id}", status_code=204)
def revoke_key(key_id: str, db: Session = Depends(get_db),
               org: Organization = Depends(current_org),
               principal: Principal = Depends(requires(Role.admin))) -> None:
    key = db.get(ApiKey, key_id)
    if key is None or key.org_id != org.id:
        raise HTTPException(404, "key not found")
    key.revoked_at = datetime.now(UTC).replace(tzinfo=None)
    db.add(AuditEvent(org_id=org.id, actor=principal.actor, action="api_key_revoked",
                      detail={"name": key.name, "prefix": key.prefix}))
    db.commit()


# --- billing ----------------------------------------------------------

class ChangePlan(BaseModel):
    plan: str


@router.post("/plan", response_model=CheckoutResult)
def change_plan(body: ChangePlan, db: Session = Depends(get_db),
                org: Organization = Depends(current_org),
                principal: Principal = Depends(requires(Role.owner))) -> CheckoutResult:
    """Start a plan change.

    With Stripe configured this returns a checkout URL and the plan changes on
    the webhook. Without it the change is applied directly and flagged as
    simulated, so the flow is demonstrable without billing credentials.
    """
    plan = PLANS.get(body.plan)
    if plan is None:
        raise HTTPException(404, f"unknown plan {body.plan!r}")
    result = start_checkout(org, plan)
    if result.applied:
        apply_plan(org, plan)
        db.add(AuditEvent(org_id=org.id, actor=principal.actor, action="plan_changed",
                          detail={"plan": plan.key, "simulated": result.simulated}))
        db.commit()
    return result

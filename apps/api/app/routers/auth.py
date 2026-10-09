from fastapi import APIRouter, Depends, HTTPException, Response
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.auth import (
    Principal,
    clear_session,
    current_principal,
    issue_session,
    optional_principal,
)
from app.core.db import get_db
from app.core.tenancy import add_member, create_org, ensure_demo_org, orgs_for
from app.models import DEFAULT_ORG_ID, Membership, Role, User

router = APIRouter(prefix="/auth", tags=["auth"])


class SignIn(BaseModel):
    name: str = Field(max_length=120, description="recorded on every approval")
    email: str | None = None
    org_name: str | None = Field(
        default=None,
        description="create a new organization owned by this user; omit to join the demo org",
    )


class OrgSummary(BaseModel):
    id: str
    name: str
    slug: str
    plan: str
    role: Role


class Me(BaseModel):
    id: str
    name: str
    email: str | None
    role: Role
    org: OrgSummary
    orgs: list[OrgSummary]


def _me(db: Session, principal: Principal) -> Me:
    user = principal.user
    memberships = orgs_for(db, user)
    summaries = [
        OrgSummary(id=o.id, name=o.name, slug=o.slug, plan=o.plan, role=r) for o, r in memberships
    ]
    return Me(
        id=user.id, name=user.name, email=user.email, role=principal.role,
        org=OrgSummary(id=principal.org.id, name=principal.org.name, slug=principal.org.slug,
                       plan=principal.org.plan, role=principal.role),
        orgs=summaries,
    )


@router.get("/me", response_model=Me | None)
def me(db: Session = Depends(get_db),
       principal: Principal | None = Depends(optional_principal)) -> Me | None:
    if principal is None or principal.user is None:
        return None
    return _me(db, principal)


@router.post("/signin", response_model=Me)
def signin(body: SignIn, response: Response, db: Session = Depends(get_db)) -> Me:
    """Sign in, creating the user on first use.

    With `org_name` the user owns a new organization; without it they join the
    demo organization as an approver, so the app is usable immediately.
    """
    name = body.name.strip()
    if not name:
        raise HTTPException(422, "a name is required")

    user = None
    if body.email:
        user = db.scalar(select(User).where(User.email == body.email))
    if user is None:
        user = db.scalar(
            select(User).join(Membership).where(User.name == name, Membership.org_id == DEFAULT_ORG_ID)
        ) if not body.org_name else None
    if user is None:
        user = User(name=name, email=body.email)
        db.add(user)
        db.commit()

    if body.org_name:
        org = create_org(db, body.org_name.strip(), user)
        role = Role.owner
    else:
        org = ensure_demo_org(db)
        role = add_member(db, org, user, Role.approver).role

    issue_session(response, user, org.id)
    return _me(db, Principal(org=org, role=role, user=user))


class SwitchOrg(BaseModel):
    org_id: str


@router.post("/switch-org", response_model=Me)
def switch_org(body: SwitchOrg, response: Response, db: Session = Depends(get_db),
               principal: Principal = Depends(current_principal)) -> Me:
    """Move the session to another organization the user belongs to."""
    if principal.user is None:
        raise HTTPException(403, "API keys are bound to one organization")
    membership = db.scalar(select(Membership).where(
        Membership.user_id == principal.user.id, Membership.org_id == body.org_id))
    if membership is None:
        raise HTTPException(404, "you are not a member of that organization")
    issue_session(response, principal.user, body.org_id)
    return _me(db, Principal(org=membership.org, role=membership.role, user=principal.user))


@router.post("/signout", status_code=204)
def signout(response: Response) -> None:
    clear_session(response)

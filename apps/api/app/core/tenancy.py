"""Organization lifecycle: create one, join one, resolve the current one."""

from __future__ import annotations

import re

from fastapi import Depends
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.auth import Principal, current_principal
from app.core.config import get_settings
from app.core.plans import DEFAULT_PLAN, apply_plan
from app.models import DEFAULT_ORG_ID, Membership, Organization, Role, User


def slugify(name: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")
    return slug or "org"


def unique_slug(db: Session, name: str) -> str:
    base = slugify(name)[:50]
    slug, n = base, 1
    while db.scalar(select(Organization).where(Organization.slug == slug)):
        n += 1
        slug = f"{base}-{n}"
    return slug


def create_org(db: Session, name: str, owner: User, org_id: str | None = None) -> Organization:
    org = Organization(name=name, slug=unique_slug(db, name))
    if org_id:
        org.id = org_id
    apply_plan(org, DEFAULT_PLAN)
    db.add(org)
    db.flush()
    db.add(Membership(org_id=org.id, user_id=owner.id, role=Role.owner))
    db.commit()
    return org


def add_member(db: Session, org: Organization, user: User, role: Role) -> Membership:
    membership = db.scalar(select(Membership).where(
        Membership.org_id == org.id, Membership.user_id == user.id))
    if membership is None:
        membership = Membership(org_id=org.id, user_id=user.id, role=role)
        db.add(membership)
    else:
        membership.role = role
    db.commit()
    return membership


def ensure_demo_org(db: Session) -> Organization:
    """The organization a fresh install starts in, so the app is usable at once."""
    settings = get_settings()
    org = db.get(Organization, DEFAULT_ORG_ID)
    if org is None:
        org = Organization(id=DEFAULT_ORG_ID, name=settings.default_org_name,
                           slug=settings.default_org_slug)
        apply_plan(org, DEFAULT_PLAN)
        db.add(org)
        db.commit()
    return org


def orgs_for(db: Session, user: User) -> list[tuple[Organization, Role]]:
    rows = db.scalars(select(Membership).where(Membership.user_id == user.id))
    return [(m.org, m.role) for m in rows]


def current_org(principal: Principal = Depends(current_principal)) -> Organization:
    """Every tenant-scoped query filters on this."""
    return principal.org


# Kept so existing imports keep working; the demo org is created at startup.
def ensure_default_org(db: Session) -> Organization:
    return ensure_demo_org(db)

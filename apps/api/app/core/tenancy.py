"""Which organization a request belongs to.

Today there is one org and it is resolved from settings, so every query is
already written as "this org's rows". When auth arrives (Phase 5/6) only this
function changes: it starts reading the session or API key instead.
"""

from fastapi import Depends
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.db import get_db
from app.models import DEFAULT_ORG_ID, Organization


def ensure_default_org(db: Session) -> Organization:
    settings = get_settings()
    org = db.get(Organization, DEFAULT_ORG_ID)
    if org is None:
        org = db.scalar(select(Organization).where(Organization.slug == settings.default_org_slug))
    if org is None:
        org = Organization(id=DEFAULT_ORG_ID, name=settings.default_org_name,
                           slug=settings.default_org_slug)
        db.add(org)
        db.commit()
    return org


def current_org(db: Session = Depends(get_db)) -> Organization:
    return ensure_default_org(db)

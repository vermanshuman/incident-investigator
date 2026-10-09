"""Who is acting, for which organization, and what they may do.

Identity comes from either a signed session cookie (a person in a browser) or
an org API key (an alerting system). Both resolve to the same thing: a
principal with an org and a role, which every route then checks.
"""

from __future__ import annotations

import hashlib
import secrets
from dataclasses import dataclass
from datetime import UTC, datetime

from fastapi import Depends, HTTPException, Request, Response
from itsdangerous import BadSignature, URLSafeSerializer
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.db import get_db
from app.models import ApiKey, Membership, Organization, Role, User

COOKIE = "investigator_session"
MAX_AGE = 60 * 60 * 24 * 14
KEY_PREFIX = "iiv"


# --- sessions ---------------------------------------------------------

def _serializer() -> URLSafeSerializer:
    return URLSafeSerializer(get_settings().session_secret, salt="session")


def issue_session(response: Response, user: User, org_id: str) -> None:
    response.set_cookie(
        COOKIE, _serializer().dumps({"user_id": user.id, "org_id": org_id}),
        max_age=MAX_AGE, httponly=True, samesite="lax",
    )


def clear_session(response: Response) -> None:
    response.delete_cookie(COOKIE)


# --- API keys ---------------------------------------------------------

def hash_secret(secret: str) -> str:
    return hashlib.sha256(secret.encode()).hexdigest()


def mint_api_key(db: Session, org: Organization, name: str, created_by: str | None) -> tuple[ApiKey, str]:
    """Return the record and the secret, which is shown once and never stored."""
    secret = f"{KEY_PREFIX}_{secrets.token_urlsafe(32)}"
    key = ApiKey(org_id=org.id, name=name, prefix=secret[: len(KEY_PREFIX) + 7],
                 hashed_secret=hash_secret(secret), created_by=created_by)
    db.add(key)
    db.commit()
    return key, secret


def _key_from_header(db: Session, request: Request) -> ApiKey | None:
    header = request.headers.get("authorization", "")
    if not header.lower().startswith("bearer "):
        return None
    secret = header[7:].strip()
    if not secret.startswith(KEY_PREFIX):
        return None
    key = db.scalar(select(ApiKey).where(ApiKey.hashed_secret == hash_secret(secret)))
    if key is None or key.revoked_at is not None:
        return None
    key.last_used_at = datetime.now(UTC)
    db.commit()
    return key


# --- principals -------------------------------------------------------

@dataclass
class Principal:
    """Whoever is making this request, and what they may do in this org."""

    org: Organization
    role: Role
    user: User | None = None
    api_key: ApiKey | None = None

    @property
    def actor(self) -> str:
        if self.user is not None:
            return self.user.name
        return f"api key {self.api_key.name}" if self.api_key else "unknown"

    @property
    def is_human(self) -> bool:
        return self.user is not None


def _session_principal(request: Request, db: Session) -> Principal | None:
    raw = request.cookies.get(COOKIE)
    if not raw:
        return None
    try:
        data = _serializer().loads(raw)
    except BadSignature:
        return None
    user = db.get(User, data.get("user_id"))
    org = db.get(Organization, data.get("org_id"))
    if user is None or org is None:
        return None
    membership = db.scalar(select(Membership).where(
        Membership.user_id == user.id, Membership.org_id == org.id))
    if membership is None:  # removed from the org since the cookie was issued
        return None
    return Principal(org=org, role=membership.role, user=user)


def optional_principal(request: Request, db: Session = Depends(get_db)) -> Principal | None:
    session = _session_principal(request, db)
    if session is not None:
        return session
    key = _key_from_header(db, request)
    if key is not None:
        # A key acts for its org with a fixed role: it may open incidents and
        # start runs, never approve - a write action needs a person.
        return Principal(org=db.get(Organization, key.org_id), role=Role.approver, api_key=key)
    return None


def current_principal(principal: Principal | None = Depends(optional_principal)) -> Principal:
    if principal is None:
        raise HTTPException(401, "sign in or present an API key")
    return principal


def requires(role: Role):
    """Dependency factory: `Depends(requires(Role.admin))`."""

    def dependency(principal: Principal = Depends(current_principal)) -> Principal:
        if not principal.role.can(role):
            raise HTTPException(
                403, f"this action needs the {role.value} role; you have {principal.role.value}")
        return principal

    return dependency


def requires_human(role: Role):
    """Like `requires`, but refuses an API key.

    Approval is the one action a machine must never take on a human's behalf.
    """

    def dependency(principal: Principal = Depends(requires(role))) -> Principal:
        if not principal.is_human:
            raise HTTPException(403, "this action must be taken by a signed-in person, not an API key")
        return principal

    return dependency

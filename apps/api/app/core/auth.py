"""Who is approving.

A signed cookie carrying a user id. Minimal on purpose: the point of this
phase is that an approval names a real person and is recorded, not that the
login is sophisticated. GitHub OAuth and roles arrive with the SaaS layer;
this is the seam they will replace.
"""

from __future__ import annotations

from fastapi import Depends, HTTPException, Request, Response
from itsdangerous import BadSignature, URLSafeSerializer
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.db import get_db
from app.models import DEFAULT_ORG_ID, User

COOKIE = "investigator_session"
MAX_AGE = 60 * 60 * 24 * 14


def _serializer() -> URLSafeSerializer:
    return URLSafeSerializer(get_settings().session_secret, salt="session")


def issue_session(response: Response, user: User) -> None:
    response.set_cookie(
        COOKIE, _serializer().dumps({"user_id": user.id}),
        max_age=MAX_AGE, httponly=True, samesite="lax",
    )


def clear_session(response: Response) -> None:
    response.delete_cookie(COOKIE)


def get_or_create_user(db: Session, name: str, email: str | None = None,
                       github_login: str | None = None) -> User:
    query = select(User).where(User.org_id == DEFAULT_ORG_ID, User.name == name)
    user = db.scalar(query)
    if user is None:
        user = User(org_id=DEFAULT_ORG_ID, name=name, email=email, github_login=github_login)
        db.add(user)
        db.commit()
    return user


def optional_user(request: Request, db: Session = Depends(get_db)) -> User | None:
    raw = request.cookies.get(COOKIE)
    if not raw:
        return None
    try:
        data = _serializer().loads(raw)
    except BadSignature:
        return None
    return db.get(User, data.get("user_id"))


def current_user(user: User | None = Depends(optional_user)) -> User:
    """Required for anything that acts on the world - approving, above all."""
    if user is None:
        raise HTTPException(401, "sign in to perform this action")
    return user

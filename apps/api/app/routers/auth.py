from fastapi import APIRouter, Depends, Response
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.core.auth import clear_session, get_or_create_user, issue_session, optional_user
from app.core.db import get_db
from app.models import User

router = APIRouter(prefix="/auth", tags=["auth"])


class SignIn(BaseModel):
    name: str = Field(max_length=120, description="the reviewer's name, recorded on approvals")
    email: str | None = None


class UserOut(BaseModel):
    id: str
    name: str
    email: str | None
    role: str

    model_config = {"from_attributes": True}


@router.get("/me", response_model=UserOut | None)
def me(user: User | None = Depends(optional_user)) -> User | None:
    return user


@router.post("/signin", response_model=UserOut)
def signin(body: SignIn, response: Response, db: Session = Depends(get_db)) -> User:
    user = get_or_create_user(db, body.name.strip(), body.email)
    issue_session(response, user)
    return user


@router.post("/signout", status_code=204)
def signout(response: Response) -> None:
    clear_session(response)

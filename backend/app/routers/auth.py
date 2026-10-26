import time
from collections import defaultdict, deque
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.security import OAuth2PasswordRequestForm
from pydantic import BaseModel, EmailStr, Field
from sqlalchemy import select

from app.models import Role, User
from app.security import DB, Admin, CurrentUser, create_token, hash_password, verify_password
from app.services import audit

router = APIRouter(prefix="/api/auth", tags=["auth"])


class UserOut(BaseModel):
    id: int
    email: str
    full_name: str
    role: str
    is_active: bool


def _out(u: User) -> UserOut:
    return UserOut(id=u.id, email=u.email, full_name=u.full_name, role=u.role, is_active=u.is_active)


# ponytail: in-memory limiter, fine for the single-process deployment; move to Redis if scaled out.
FAILED: dict[str, deque[float]] = defaultdict(deque)
MAX_FAILURES, WINDOW_S = 10, 15 * 60


def _too_many(key: str) -> bool:
    q, now = FAILED[key], time.monotonic()
    while q and now - q[0] > WINDOW_S:
        q.popleft()
    return len(q) >= MAX_FAILURES


@router.post("/login")
def login(form: Annotated[OAuth2PasswordRequestForm, Depends()], request: Request, db: DB):
    email = form.username.lower().strip()
    key = f"{request.client.host if request.client else '?'}|{email}"
    if _too_many(key):
        raise HTTPException(429, "Too many failed sign-in attempts. Try again in 15 minutes.")
    user = db.scalar(select(User).where(User.email == email))
    if not user or not user.is_active or not verify_password(form.password, user.password_hash):
        FAILED[key].append(time.monotonic())
        raise HTTPException(401, "Incorrect email or password.")
    FAILED.pop(key, None)
    return {"access_token": create_token(user), "token_type": "bearer", "user": _out(user)}


@router.get("/me")
def me(user: CurrentUser) -> UserOut:
    return _out(user)


class UserIn(BaseModel):
    email: EmailStr
    full_name: str = ""
    password: str = Field(min_length=10)
    role: Role = Role.viewer


class UserPatch(BaseModel):
    role: Role | None = None
    is_active: bool | None = None


@router.get("/users")
def list_users(_: Admin, db: DB) -> list[UserOut]:
    return [_out(u) for u in db.scalars(select(User).order_by(User.id))]


@router.post("/users", status_code=201)
def create_user(body: UserIn, admin: Admin, db: DB) -> UserOut:
    email = body.email.lower()
    if db.scalar(select(User).where(User.email == email)):
        raise HTTPException(409, "A user with this email already exists.")
    u = User(email=email, full_name=body.full_name, password_hash=hash_password(body.password), role=body.role)
    db.add(u)
    db.flush()
    audit.record(db, admin, "create", "user", u.id, f"{u.email} as {u.role}")
    db.commit()
    return _out(u)


@router.patch("/users/{user_id}")
def update_user(user_id: int, body: UserPatch, admin: Admin, db: DB) -> UserOut:
    u = db.get(User, user_id)
    if not u:
        raise HTTPException(404, "User not found.")
    if u.id == admin.id and (body.role not in (None, Role.admin) or body.is_active is False):
        raise HTTPException(400, "You cannot demote or disable your own account.")
    if body.role is not None:
        u.role = body.role
    if body.is_active is not None:
        u.is_active = body.is_active
    audit.record(db, admin, "update", "user", u.id, f"{u.email}: {body.model_dump(exclude_none=True)}")
    db.commit()
    return _out(u)

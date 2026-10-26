from datetime import UTC, datetime, timedelta
from typing import Annotated

import jwt
from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from pwdlib import PasswordHash
from sqlalchemy.orm import Session

from app.config import get_settings
from app.db import get_db
from app.models import Role, User

hasher = PasswordHash.recommended()
oauth2 = OAuth2PasswordBearer(tokenUrl="/api/auth/login")
RANK = {Role.viewer: 0, Role.analyst: 1, Role.admin: 2}


def hash_password(pw: str) -> str:
    return hasher.hash(pw)


def verify_password(pw: str, hashed: str) -> bool:
    return hasher.verify(pw, hashed)


def create_token(user: User) -> str:
    s = get_settings()
    exp = datetime.now(UTC) + timedelta(minutes=s.jwt_ttl_minutes)
    return jwt.encode({"sub": str(user.id), "role": user.role, "exp": exp}, s.jwt_secret, algorithm="HS256")


def current_user(token: Annotated[str, Depends(oauth2)], db: Annotated[Session, Depends(get_db)]) -> User:
    try:
        payload = jwt.decode(token, get_settings().jwt_secret, algorithms=["HS256"])
    except jwt.PyJWTError:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Session expired. Please sign in again.") from None
    user = db.get(User, int(payload["sub"]))
    if not user or not user.is_active:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Account not found or disabled.")
    return user


def require(min_role: Role):
    def dep(user: Annotated[User, Depends(current_user)]) -> User:
        if RANK[Role(user.role)] < RANK[min_role]:
            raise HTTPException(status.HTTP_403_FORBIDDEN, f"Requires {min_role.value} role.")
        return user

    return dep


CurrentUser = Annotated[User, Depends(current_user)]
Analyst = Annotated[User, Depends(require(Role.analyst))]
Admin = Annotated[User, Depends(require(Role.admin))]
DB = Annotated[Session, Depends(get_db)]

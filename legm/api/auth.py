"""Email + password accounts with JWT bearer tokens.

Environment:
  LEGM_SECRET_KEY      HMAC secret for tokens (a dev default is used, with a warning, if unset)
  LEGM_TOKEN_TTL_HOURS token lifetime (default 168 = 7 days)
  LEGM_INVITE_CODE     if set, registration requires this code
"""

from __future__ import annotations

import logging
import os
import re
from datetime import UTC, datetime, timedelta

import bcrypt
import jwt
from pydantic import BaseModel, EmailStr, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from legm.data.models import User

log = logging.getLogger(__name__)

DEV_SECRET = "legm-dev-secret-change-me"
ALGORITHM = "HS256"
_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


class AuthSettings:
    def __init__(self, secret: str | None = None, ttl_hours: int | None = None, invite_code: str | None = None):
        self.secret = secret or os.environ.get("LEGM_SECRET_KEY") or DEV_SECRET
        if self.secret == DEV_SECRET:
            log.warning("LEGM_SECRET_KEY not set; using the development secret. Set it before sharing the app.")
        self.ttl = timedelta(hours=ttl_hours or int(os.environ.get("LEGM_TOKEN_TTL_HOURS", "168")))
        self.invite_code = invite_code if invite_code is not None else os.environ.get("LEGM_INVITE_CODE") or None


class RegisterIn(BaseModel):
    email: EmailStr
    password: str = Field(min_length=8, max_length=128)
    display_name: str = Field(min_length=1, max_length=80)
    invite_code: str | None = None


class LoginIn(BaseModel):
    email: EmailStr
    password: str


class UserOut(BaseModel):
    id: int
    email: str
    display_name: str


class TokenOut(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user: UserOut


class AuthError(Exception):
    def __init__(self, status: int, detail: str):
        super().__init__(detail)
        self.status = status
        self.detail = detail


def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def verify_password(password: str, password_hash: str) -> bool:
    try:
        return bcrypt.checkpw(password.encode("utf-8"), password_hash.encode("utf-8"))
    except ValueError:
        return False


def create_token(user: User, settings: AuthSettings, now: datetime | None = None) -> str:
    now = now or datetime.now(UTC)
    payload = {"sub": str(user.id), "email": user.email, "iat": int(now.timestamp()), "exp": int((now + settings.ttl).timestamp())}
    return jwt.encode(payload, settings.secret, algorithm=ALGORITHM)


def decode_token(token: str, settings: AuthSettings) -> int:
    """Return the user id or raise AuthError(401)."""
    try:
        payload = jwt.decode(token, settings.secret, algorithms=[ALGORITHM])
        return int(payload["sub"])
    except (jwt.PyJWTError, KeyError, ValueError) as exc:
        raise AuthError(401, "invalid or expired token") from exc


def register_user(session: Session, body: RegisterIn, settings: AuthSettings) -> User:
    if settings.invite_code and body.invite_code != settings.invite_code:
        raise AuthError(403, "a valid invite code is required to register")
    email = body.email.lower().strip()
    if session.execute(select(User).where(User.email == email)).scalar_one_or_none():
        raise AuthError(409, "an account with that email already exists")
    user = User(email=email, display_name=body.display_name.strip(), password_hash=hash_password(body.password))
    session.add(user)
    session.flush()
    return user


def authenticate(session: Session, email: str, password: str) -> User:
    user = session.execute(select(User).where(User.email == email.lower().strip())).scalar_one_or_none()
    if user is None or not user.is_active or not verify_password(password, user.password_hash):
        raise AuthError(401, "incorrect email or password")
    return user


def user_out(user: User) -> UserOut:
    return UserOut(id=user.id, email=user.email, display_name=user.display_name)

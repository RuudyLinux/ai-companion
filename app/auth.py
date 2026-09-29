"""
Session auth. The cookie holds a short JWT that only identifies a server-side
`user_sessions` row; the row is the source of truth, so logout, role changes and
account deletion can revoke a session immediately instead of waiting for expiry.
"""

from datetime import timedelta

import bcrypt
from fastapi import Depends, HTTPException, Request, Response, status
from jose import JWTError, jwt
from sqlalchemy.orm import Session

from core.config import settings
from core.errors import Forbidden, Unauthorized
from database import get_db
from models import User, UserSession, as_utc, now

JWT_ALGORITHM = "HS256"
COOKIE_NAME = "session"
LAST_SEEN_RESOLUTION = timedelta(minutes=5)

ROLE_HIERARCHY = {"user": 0, "admin": 1, "super_admin": 2}

PASSWORD_MIN_LENGTH = 8
PASSWORD_MAX_BYTES = 72  # bcrypt ignores everything past 72 bytes


def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def verify_password(password: str, hashed: str) -> bool:
    try:
        return bcrypt.checkpw(password.encode("utf-8")[:PASSWORD_MAX_BYTES], hashed.encode("utf-8"))
    except ValueError:
        return False


# a real hash, so failed logins for unknown emails cost the same time as wrong passwords
_DUMMY_HASH = hash_password("timing-equaliser-not-a-real-password")


def verify_password_or_dummy(password: str, user: User | None) -> bool:
    if user is None:
        verify_password(password, _DUMMY_HASH)
        return False
    return verify_password(password, user.hashed_password)


def create_session(db: Session, user: User, request: Request | None = None) -> str:
    """Creates a new server-side session and returns the signed cookie value."""
    issued = now()
    expires = issued + timedelta(seconds=settings.session_ttl_seconds)
    user_agent = request.headers.get("user-agent", "")[:255] if request else None
    session_row = UserSession(user_id=user.id, expires_at=expires, last_seen_at=issued, user_agent=user_agent)
    db.add(session_row)
    db.commit()
    return jwt.encode(
        {"sub": user.id, "sid": session_row.id, "iat": issued, "exp": expires, "typ": "session"},
        settings.jwt_secret,
        algorithm=JWT_ALGORITHM,
    )


def _decode(token: str) -> dict | None:
    try:
        payload = jwt.decode(token, settings.jwt_secret, algorithms=[JWT_ALGORITHM])
    except JWTError:
        return None
    if payload.get("typ") != "session" or not payload.get("sub") or not payload.get("sid"):
        return None
    return payload


def set_session_cookie(response: Response, token: str) -> None:
    response.set_cookie(
        COOKIE_NAME,
        token,
        httponly=True,
        secure=settings.cookie_secure,
        samesite="lax",
        max_age=settings.session_ttl_seconds,
        path="/",
    )


def clear_session_cookie(response: Response) -> None:
    response.delete_cookie(COOKIE_NAME, path="/", secure=settings.cookie_secure, httponly=True, samesite="lax")


def revoke_session(db: Session, session_id: str) -> None:
    db.query(UserSession).filter(UserSession.id == session_id, UserSession.revoked_at.is_(None)).update(
        {UserSession.revoked_at: now()}, synchronize_session=False
    )


def revoke_all_sessions(db: Session, user_id: str, except_session_id: str | None = None) -> None:
    query = db.query(UserSession).filter(UserSession.user_id == user_id, UserSession.revoked_at.is_(None))
    if except_session_id:
        query = query.filter(UserSession.id != except_session_id)
    query.update({UserSession.revoked_at: now()}, synchronize_session=False)


def current_session_id(request: Request) -> str | None:
    token = request.cookies.get(COOKIE_NAME)
    payload = _decode(token) if token else None
    return payload["sid"] if payload else None


def get_current_user(request: Request, db: Session = Depends(get_db)) -> User | None:
    if hasattr(request.state, "user"):
        return request.state.user

    user = None
    token = request.cookies.get(COOKIE_NAME)
    payload = _decode(token) if token else None
    if payload:
        session_row = db.get(UserSession, payload["sid"])
        current = now()
        if (
            session_row is not None
            and session_row.user_id == payload["sub"]
            and session_row.revoked_at is None
            and as_utc(session_row.expires_at) > current
        ):
            user = db.get(User, session_row.user_id)
            last_seen = as_utc(session_row.last_seen_at)
            if user is not None and (last_seen is None or current - last_seen > LAST_SEEN_RESOLUTION):
                session_row.last_seen_at = current
                db.commit()

    request.state.user = user
    request.state.user_id = user.id if user else None
    return user


def require_user(request: Request, db: Session = Depends(get_db)) -> User:
    """For page routes: bounce anonymous visitors to the login page."""
    user = get_current_user(request, db)
    if not user:
        raise HTTPException(status_code=status.HTTP_303_SEE_OTHER, headers={"Location": "/login"})
    return user


def require_user_api(request: Request, db: Session = Depends(get_db)) -> User:
    """For fetch()-based JSON endpoints: 401 instead of a page redirect."""
    user = get_current_user(request, db)
    if not user:
        raise Unauthorized()
    return user


def has_role(user: User, minimum_role: str) -> bool:
    return ROLE_HIERARCHY.get(user.role, 0) >= ROLE_HIERARCHY[minimum_role]


def require_role(minimum_role: str, api: bool = False):
    def dependency(request: Request, db: Session = Depends(get_db)) -> User:
        user = require_user_api(request, db) if api else require_user(request, db)
        if not has_role(user, minimum_role):
            raise Forbidden("You don't have permission to do that.")
        return user

    return dependency

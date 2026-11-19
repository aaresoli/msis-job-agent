"""FastAPI dependencies for database sessions, identity, and service auth."""

from __future__ import annotations

import hashlib
import hmac
from collections.abc import Iterator
from datetime import UTC, datetime
from functools import lru_cache
from uuid import UUID

from fastapi import Cookie, Depends, Header, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from hope_job_agent.db.platform_models import User, UserSession
from hope_job_agent.db.session import create_db_engine, create_session_factory
from hope_job_agent.platform.settings import PlatformSettings, get_platform_settings


@lru_cache
def _engine() -> Engine:
    return create_db_engine(storage="postgres")


@lru_cache
def _session_factory() -> sessionmaker[Session]:
    return create_session_factory(_engine())


def get_db() -> Iterator[Session]:
    session = _session_factory()()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def _token_hash(token: str, pepper: str) -> str:
    return hashlib.sha256(f"{pepper}:{token}".encode()).hexdigest()


def current_user(
    request: Request,
    db: Session = Depends(get_db),
    settings: PlatformSettings = Depends(get_platform_settings),
    session_token: str | None = Cookie(default=None, alias="hope_session"),
) -> User:
    token = session_token or request.cookies.get(settings.session_cookie_name)
    if not token:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED)
    token_hash = _token_hash(token, settings.auth_pepper.get_secret_value())
    session = db.scalar(
        select(UserSession).where(
            UserSession.token_hash == token_hash,
            UserSession.revoked_at.is_(None),
            UserSession.expires_at > datetime.now(UTC),
        )
    )
    if session is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED)
    user = db.get(User, session.user_id)
    if user is None or user.status == "disabled":
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED)
    now = datetime.now(UTC)
    session.last_seen_at = now
    request.state.session = session
    return user


def require_csrf(
    request: Request,
    user: User = Depends(current_user),
    csrf_token: str | None = Header(default=None, alias="X-CSRF-Token"),
    settings: PlatformSettings = Depends(get_platform_settings),
) -> User:
    session: UserSession = request.state.session
    supplied = csrf_token or request.headers.get(settings.csrf_header_name)
    if not supplied:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="CSRF token")
    expected = _token_hash(supplied, settings.auth_pepper.get_secret_value())
    if not hmac.compare_digest(expected, session.csrf_token_hash):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="CSRF token")
    return user


def require_gcs(user: User = Depends(current_user)) -> User:
    if user.role not in {"gcs", "admin"}:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN)
    return user


def require_internal_service(
    request: Request,
    authorization: str | None = Header(default=None),
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    request_id: str | None = Header(default=None, alias="X-Request-ID"),
    settings: PlatformSettings = Depends(get_platform_settings),
) -> None:
    prefix = "Bearer "
    candidate = (
        authorization[len(prefix) :]
        if authorization and authorization.startswith(prefix)
        else ""
    )
    expected = settings.internal_service_token.get_secret_value()
    if not expected or not hmac.compare_digest(candidate, expected):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED)
    if request.method in {"POST", "PUT", "PATCH", "DELETE"}:
        if not idempotency_key or not request_id:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Idempotency-Key and X-Request-ID are required",
            )
        request.state.idempotency_key = idempotency_key


def uuid_or_404(value: str) -> UUID:
    try:
        return UUID(value)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND) from exc

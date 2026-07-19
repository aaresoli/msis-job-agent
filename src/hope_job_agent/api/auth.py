"""Passwordless authentication routes."""

from __future__ import annotations

from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from sqlalchemy.orm import Session

from hope_job_agent.api.dependencies import current_user, get_db, require_csrf
from hope_job_agent.api.schemas import (
    MagicLinkConsume,
    MagicLinkRequest,
    MessageResponse,
    SessionResponse,
)
from hope_job_agent.db.platform_models import User, UserSession
from hope_job_agent.platform.audit import record_audit
from hope_job_agent.platform.auth import (
    InvalidLoginToken,
    consume_magic_link,
    issue_magic_link,
    rotate_session,
)
from hope_job_agent.platform.rate_limit import allow_request
from hope_job_agent.platform.settings import PlatformSettings, get_platform_settings

router = APIRouter(prefix="/auth", tags=["authentication"])


@router.post("/magic-link/request", response_model=MessageResponse)
def request_magic_link(
    payload: MagicLinkRequest,
    request: Request,
    db: Session = Depends(get_db),
    settings: PlatformSettings = Depends(get_platform_settings),
) -> MessageResponse:
    client_ip = request.client.host if request.client else "unknown"
    allowed = allow_request(
        bucket="magic-link",
        identity=f"{client_ip}:{payload.email}",
        limit=settings.magic_link_rate_limit_per_hour,
        window_seconds=3600,
        redis_url=settings.redis_url,
    )
    if allowed:
        issue_magic_link(
            db,
            email=payload.email,
            settings=settings,
            requested_ip=client_ip,
        )
    return MessageResponse(
        message="If that invited account exists, a sign-in link is on its way."
    )


@router.post("/magic-link/consume", response_model=SessionResponse)
def consume_link(
    payload: MagicLinkConsume,
    response: Response,
    db: Session = Depends(get_db),
    settings: PlatformSettings = Depends(get_platform_settings),
) -> SessionResponse:
    try:
        user, session_token, csrf_token = consume_magic_link(
            db, token=payload.token, settings=settings
        )
    except InvalidLoginToken as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)
        ) from exc
    response.set_cookie(
        settings.session_cookie_name,
        session_token,
        httponly=True,
        secure=settings.app_base_url.startswith("https://"),
        samesite="lax",
        max_age=settings.session_ttl_days * 86400,
        path="/",
    )
    record_audit(
        db,
        actor_user_id=user.id,
        subject_user_id=user.id,
        action="auth.login",
        resource_type="session",
    )
    return SessionResponse(
        user_id=user.id,
        email=user.email,
        display_name=user.display_name,
        role=user.role,
        csrf_token=csrf_token,
    )


@router.get("/session", response_model=SessionResponse)
def get_session(
    user: User = Depends(current_user),
) -> SessionResponse:
    return SessionResponse(
        user_id=user.id,
        email=user.email,
        display_name=user.display_name,
        role=user.role,
    )


@router.post("/session/rotate", response_model=SessionResponse)
def rotate_current_session(
    request: Request,
    response: Response,
    user: User = Depends(require_csrf),
    settings: PlatformSettings = Depends(get_platform_settings),
) -> SessionResponse:
    session: UserSession = request.state.session
    raw_session, csrf_token = rotate_session(session, settings=settings)
    response.set_cookie(
        settings.session_cookie_name,
        raw_session,
        httponly=True,
        secure=settings.app_base_url.startswith("https://"),
        samesite="lax",
        max_age=settings.session_ttl_days * 86400,
        path="/",
    )
    return SessionResponse(
        user_id=user.id,
        email=user.email,
        display_name=user.display_name,
        role=user.role,
        csrf_token=csrf_token,
    )


@router.post("/logout", response_model=MessageResponse)
def logout(
    request: Request,
    response: Response,
    user: User = Depends(require_csrf),
    settings: PlatformSettings = Depends(get_platform_settings),
    db: Session = Depends(get_db),
) -> MessageResponse:
    session: UserSession = request.state.session
    session.revoked_at = datetime.now(UTC)
    response.delete_cookie(settings.session_cookie_name, path="/")
    record_audit(
        db,
        actor_user_id=user.id,
        subject_user_id=user.id,
        action="auth.logout",
        resource_type="session",
        resource_id=str(session.id),
    )
    return MessageResponse(message="Signed out")

"""Passwordless authentication and provider-neutral session management."""

from __future__ import annotations

import hashlib
import secrets
import smtplib
from datetime import UTC, datetime, timedelta
from email.message import EmailMessage

from sqlalchemy import select
from sqlalchemy.orm import Session

from hope_job_agent.db.platform_models import LoginToken, User, UserSession
from hope_job_agent.platform.settings import PlatformSettings


class InvalidLoginToken(ValueError):
    pass


def hash_secret(value: str, pepper: str) -> str:
    return hashlib.sha256(f"{pepper}:{value}".encode()).hexdigest()


def issue_magic_link(
    db: Session,
    *,
    email: str,
    settings: PlatformSettings,
    requested_ip: str | None = None,
) -> str | None:
    normalized = email.strip().casefold()
    if settings.allowed_email_domains:
        domain = normalized.rsplit("@", 1)[-1]
        if domain not in {item.casefold() for item in settings.allowed_email_domains}:
            return None
    user = db.scalar(select(User).where(User.email == normalized))
    if user is None or user.status == "disabled":
        return None
    raw = secrets.token_urlsafe(48)
    pepper = settings.auth_pepper.get_secret_value()
    db.add(
        LoginToken(
            user_id=user.id,
            token_hash=hash_secret(raw, pepper),
            expires_at=datetime.now(UTC)
            + timedelta(minutes=settings.magic_link_ttl_minutes),
            requested_ip_hash=(
                hash_secret(requested_ip, pepper) if requested_ip else None
            ),
        )
    )
    _send_magic_link(user.email, raw, settings)
    return raw


def consume_magic_link(
    db: Session, *, token: str, settings: PlatformSettings
) -> tuple[User, str, str]:
    now = datetime.now(UTC)
    pepper = settings.auth_pepper.get_secret_value()
    record = db.scalar(
        select(LoginToken).where(
            LoginToken.token_hash == hash_secret(token, pepper),
            LoginToken.used_at.is_(None),
            LoginToken.expires_at > now,
        )
    )
    if record is None:
        raise InvalidLoginToken("Login link is invalid or expired")
    user = db.get(User, record.user_id)
    if user is None or user.status == "disabled":
        raise InvalidLoginToken("Login link is invalid or expired")
    record.used_at = now
    session_token = secrets.token_urlsafe(48)
    csrf_token = secrets.token_urlsafe(32)
    db.add(
        UserSession(
            user_id=user.id,
            token_hash=hash_secret(session_token, pepper),
            csrf_token_hash=hash_secret(csrf_token, pepper),
            expires_at=now + timedelta(days=settings.session_ttl_days),
        )
    )
    user.status = "active"
    user.last_login_at = now
    return user, session_token, csrf_token


def rotate_session(
    session: UserSession, *, settings: PlatformSettings
) -> tuple[str, str]:
    """Rotate both bearer and CSRF secrets without changing the user identity."""

    raw_session = secrets.token_urlsafe(48)
    raw_csrf = secrets.token_urlsafe(32)
    pepper = settings.auth_pepper.get_secret_value()
    session.token_hash = hash_secret(raw_session, pepper)
    session.csrf_token_hash = hash_secret(raw_csrf, pepper)
    session.expires_at = datetime.now(UTC) + timedelta(days=settings.session_ttl_days)
    session.last_seen_at = datetime.now(UTC)
    return raw_session, raw_csrf


def _send_magic_link(email: str, token: str, settings: PlatformSettings) -> None:
    if not settings.smtp_host:
        return
    message = EmailMessage()
    message["Subject"] = "Your HOPE Career Intelligence sign-in link"
    message["From"] = settings.smtp_from
    message["To"] = email
    link = f"{settings.app_base_url.rstrip('/')}/auth/consume?token={token}"
    message.set_content(
        "Use this one-time link to sign in. It expires in "
        f"{settings.magic_link_ttl_minutes} minutes:\n\n{link}"
    )
    with smtplib.SMTP(settings.smtp_host, settings.smtp_port, timeout=15) as client:
        client.starttls()
        password = settings.smtp_password.get_secret_value()
        if settings.smtp_username:
            client.login(settings.smtp_username, password)
        client.send_message(message)

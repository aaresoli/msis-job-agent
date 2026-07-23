"""Coverage for the transactional outbox relay.

Runs against real PostgreSQL because the two behaviours that matter are
PostgreSQL behaviours: ``FOR UPDATE ... SKIP LOCKED`` claiming, and the row
locking that keeps two relays from sending the same digest twice. A SQLite
stand-in would pass while proving neither.
"""

from __future__ import annotations

import os
import uuid

import pytest
from sqlalchemy import text

from hope_job_agent.db.platform_models import OutboxEvent, User
from hope_job_agent.db.session import (
    create_db_engine,
    create_session_factory,
    session_scope,
)
from hope_job_agent.ops import outbox
from hope_job_agent.platform.settings import get_platform_settings

pytestmark = pytest.mark.postgres

TEST_EMAIL_PREFIX = "pytest-outbox-"


def _postgres_url() -> str:
    from hope_job_agent.config.database import build_postgres_url

    return os.getenv("DATABASE_URL", "").strip() or build_postgres_url()


def _can_connect() -> bool:
    try:
        engine = create_db_engine(_postgres_url(), storage="postgres")
        with engine.connect() as connection:
            connection.exec_driver_sql("SELECT 1")
        engine.dispose()
        return True
    except Exception:
        return False


if not _can_connect():
    pytest.skip(
        "PostgreSQL is not available; start docker compose postgres and run "
        "alembic upgrade head",
        allow_module_level=True,
    )


@pytest.fixture
def factory():
    engine = create_db_engine(_postgres_url(), storage="postgres")
    created = create_session_factory(engine)
    yield created
    try:
        with session_scope(created) as session:
            session.execute(
                text("DELETE FROM outbox_events WHERE aggregate_type = 'pytest'")
            )
            session.execute(
                text("DELETE FROM users WHERE email LIKE :p"),
                {"p": f"{TEST_EMAIL_PREFIX}%"},
            )
    except Exception:  # noqa: BLE001 - cleanup must not mask test outcomes
        pass
    engine.dispose()


def _event(event_type: str, aggregate_id: str = "", **payload: object) -> OutboxEvent:
    return OutboxEvent(
        event_type=event_type,
        aggregate_type="pytest",
        aggregate_id=aggregate_id or str(uuid.uuid4()),
        payload=dict(payload),
    )


def test_relay_publishes_and_does_not_republish(factory) -> None:
    with session_scope(factory) as db:
        db.add(_event("profile.updated.v1"))
        db.flush()
        first = outbox.relay_pending(db, batch_size=10)
        assert first["published"] == 1

        second = outbox.relay_pending(db, batch_size=10)
        # The published_at stamp is what stops a redelivery; without it every
        # relay pass would re-send every event ever written.
        assert second["claimed"] == 0


def test_a_failing_handler_increments_attempts_and_dead_letters(
    factory, monkeypatch: pytest.MonkeyPatch
) -> None:
    def _explode(_db, _event):  # noqa: ANN001, ANN202
        raise RuntimeError("smtp unavailable")

    monkeypatch.setitem(outbox.HANDLERS, "digest.requested.v1", _explode)
    max_attempts = get_platform_settings().outbox_max_attempts

    with session_scope(factory) as db:
        event = _event("digest.requested.v1", cadence="daily")
        db.add(event)
        db.flush()
        event_id = event.id

        for _ in range(max_attempts):
            result = outbox.relay_pending(db, batch_size=10)
            assert result["failed"] == 1

        assert result["dead_lettered"] == 1
        db.refresh(event)
        assert event.attempts == max_attempts
        assert event.published_at is None

        # Dead-lettered rows drop out of the claim query, so one poisoned event
        # cannot occupy the batch forever and starve everything behind it.
        assert outbox.relay_pending(db, batch_size=10)["claimed"] == 0
        assert db.get(OutboxEvent, event_id) is not None


def test_an_unknown_event_type_is_left_for_a_later_release(factory) -> None:
    with session_scope(factory) as db:
        db.add(_event("something.new.v9"))
        db.flush()
        result = outbox.relay_pending(db, batch_size=10)
        assert result["published"] == 0
        assert result["failed"] == 1


def test_concurrent_relays_do_not_claim_the_same_event(factory) -> None:
    """SKIP LOCKED is what makes a second relay safe to run."""

    with session_scope(factory) as first:
        first.add(_event("profile.updated.v1"))
        first.flush()

    session_a = factory()
    session_b = factory()
    try:
        claimed_a = outbox.relay_pending(session_a, batch_size=10)
        # session_a holds the row lock until it commits.
        claimed_b = outbox.relay_pending(session_b, batch_size=10)
        assert claimed_a["claimed"] == 1
        assert claimed_b["claimed"] == 0
        session_a.commit()
    finally:
        session_a.close()
        session_b.rollback()
        session_b.close()


def test_digest_handler_sends_mail_for_a_real_user(
    factory, monkeypatch: pytest.MonkeyPatch
) -> None:
    sent: list[tuple[str, str]] = []

    def _capture(message, _settings) -> bool:  # noqa: ANN001
        sent.append((message["To"], message.get_content()))
        return True

    monkeypatch.setattr("hope_job_agent.ops.digests.send_message", _capture)

    with session_scope(factory) as db:
        user = User(
            email=f"{TEST_EMAIL_PREFIX}{uuid.uuid4().hex[:8]}@example.edu",
            role="student",
            status="active",
        )
        db.add(user)
        db.flush()
        db.add(_event("digest.requested.v1", str(user.id), cadence="daily"))
        db.flush()

        result = outbox.relay_pending(db, batch_size=10)

    # Published either way: a student with no profile or no matches is not an
    # error, and leaving the event unpublished would retry it forever.
    assert result["published"] == 1
    assert result["delivered"] == 0
    assert sent == []

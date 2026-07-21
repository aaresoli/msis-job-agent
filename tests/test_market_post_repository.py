"""PostgreSQL integration tests for the market-post repository.

Requires a running Postgres with migrations applied (``market_posts`` exists).
Skips cleanly when Postgres is unavailable, matching test_postgres_integration.
"""

from __future__ import annotations

import hashlib
import os
from datetime import UTC, datetime

import pytest
from sqlalchemy import delete, select

from hope_job_agent.config.database import build_postgres_url
from hope_job_agent.db.platform_models import MarketPost
from hope_job_agent.db.session import (
    create_db_engine,
    create_session_factory,
    session_scope,
)
from hope_job_agent.persistence.market_post_repository import MarketPostRepository

pytestmark = pytest.mark.postgres


def _postgres_url() -> str:
    explicit = os.getenv("DATABASE_URL", "").strip()
    return explicit or build_postgres_url()


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

_SOURCE = "apify_linkedin_posts_test"


@pytest.fixture
def session_factory():
    engine = create_db_engine(_postgres_url(), storage="postgres")
    factory = create_session_factory(engine)
    with session_scope(factory) as db:
        db.execute(delete(MarketPost).where(MarketPost.source == _SOURCE))
    yield factory
    with session_scope(factory) as db:
        db.execute(delete(MarketPost).where(MarketPost.source == _SOURCE))
    engine.dispose()


def _post(external_id: str, content: str) -> dict:
    return {
        "source": _SOURCE,
        "external_id": external_id,
        "author_name": "Jane Doe",
        "company_name": "Cubit Capital",
        "content": content,
        "source_url": f"https://linkedin.com/posts/{external_id}",
        "published_at": datetime.now(UTC),
        "content_hash": hashlib.sha256(content.encode()).hexdigest(),
        "raw_metadata": {"msis_relevance": {"score": 4}},
    }


def test_insert_then_dedup_and_update(session_factory) -> None:  # noqa: ANN001
    with session_scope(session_factory) as db:
        first = MarketPostRepository(db).upsert_many(
            [_post("p1", "Hiring a data analyst.")]
        )
    assert (first.inserted, first.updated, first.unchanged) == (1, 0, 0)

    # Re-ingesting the identical post is a no-op.
    with session_scope(session_factory) as db:
        again = MarketPostRepository(db).upsert_many(
            [_post("p1", "Hiring a data analyst.")]
        )
    assert (again.inserted, again.updated, again.unchanged) == (0, 0, 1)

    # Changed content updates the existing row in place.
    with session_scope(session_factory) as db:
        changed = MarketPostRepository(db).upsert_many(
            [_post("p1", "Hiring TWO data analysts.")]
        )
    assert (changed.inserted, changed.updated, changed.unchanged) == (0, 1, 0)

    with session_scope(session_factory) as db:
        rows = list(
            db.scalars(select(MarketPost).where(MarketPost.source == _SOURCE))
        )
        assert len(rows) == 1
        assert rows[0].content == "Hiring TWO data analysts."

"""SQLAlchemy session factory and engine helpers."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager

from sqlalchemy import create_engine
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from hope_job_agent.config.database import mask_database_url, resolve_database_url


def create_db_engine(
    database_url: str | None = None,
    *,
    storage: str = "auto",
    echo: bool = False,
) -> Engine:
    """Create a SQLAlchemy engine for the resolved database URL."""

    url = resolve_database_url(database_url, storage=storage)
    if not _is_postgres_url(url):
        raise ValueError(
            "PostgreSQL engine requested but resolved URL is not PostgreSQL: "
            f"{mask_database_url(url)}"
        )
    return create_engine(url, echo=echo, pool_pre_ping=True)


def create_session_factory(engine: Engine) -> sessionmaker[Session]:
    """Return a sessionmaker bound to ``engine``."""

    return sessionmaker(bind=engine, autoflush=False, autocommit=False)


@contextmanager
def session_scope(session_factory: sessionmaker[Session]) -> Iterator[Session]:
    """Provide a transactional session scope."""

    session = session_factory()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def _is_postgres_url(url: str) -> bool:
    scheme = url.split("://", 1)[0].casefold()
    return scheme.startswith("postgres")

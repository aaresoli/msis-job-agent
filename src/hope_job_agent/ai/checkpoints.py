"""Private PostgreSQL checkpoint lifecycle for LangGraph workflows."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager

from langgraph.checkpoint.postgres import PostgresSaver

from hope_job_agent.platform.settings import get_platform_settings


def _psycopg_url(url: str) -> str:
    return url.replace("postgresql+psycopg://", "postgresql://", 1)


@contextmanager
def postgres_checkpointer(*, setup: bool = False) -> Iterator[PostgresSaver | None]:
    """Yield a saver when configured; otherwise keep local development stateless."""

    configured = (
        get_platform_settings().langgraph_database_url.get_secret_value().strip()
    )
    if not configured:
        yield None
        return
    with PostgresSaver.from_conn_string(_psycopg_url(configured)) as saver:
        if setup:
            saver.setup()
        yield saver


def delete_checkpoint_thread(thread_id: str) -> None:
    """Delete all durable state for a private workflow thread."""

    with postgres_checkpointer() as saver:
        if saver is not None:
            saver.delete_thread(thread_id)


def main() -> int:
    with postgres_checkpointer(setup=True) as saver:
        if saver is None:
            raise RuntimeError("LANGGRAPH_DATABASE_URL is required")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

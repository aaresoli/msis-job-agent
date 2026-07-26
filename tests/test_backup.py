"""Coverage for the backup task.

Split in two on purpose. The helpers that decide *what* gets kept and how it is
identified are pure and always run. The full dump/restore/verify cycle needs the
PostgreSQL client binaries at the server's major version, so it skips where they
are absent rather than pretending to have tested a backup it never took.
"""

from __future__ import annotations

import gzip
import os
import shutil
import subprocess
import tarfile
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy import text

from hope_job_agent.ops import backup

unit = pytest.mark.unit


@unit
def test_archive_name_sorts_chronologically() -> None:
    """Object keys are listed lexicographically; the name has to sort by time."""

    early = backup._archive_name(datetime(2026, 7, 21, 1, 0, tzinfo=UTC))
    late = backup._archive_name(datetime(2026, 7, 21, 23, 0, tzinfo=UTC))

    assert early < late
    assert early.endswith(".tar.gz")


@unit
def test_password_travels_in_the_environment_not_argv() -> None:
    """Command lines are world-readable in ps; PGPASSWORD is not."""

    from sqlalchemy.engine import make_url

    url = make_url("postgresql+psycopg://hope_user:hunter2@db:5432/hope_jobs")

    env = backup._pg_env(url)
    flags = backup._connection_flags(url)

    assert env["PGPASSWORD"] == "hunter2"
    assert "hunter2" not in " ".join(flags)
    assert "--no-password" in flags


@unit
def test_digest_matches_the_file_contents(tmp_path: Path) -> None:
    import hashlib

    archive = tmp_path / "archive.tar.gz"
    payload = b"backup payload" * 1000
    archive.write_bytes(payload)

    digest, size = backup._digest(archive)

    assert digest == hashlib.sha256(payload).hexdigest()
    assert size == len(payload)


@unit
def test_bundle_contains_both_the_dump_and_the_globals(tmp_path: Path) -> None:
    """Roles live outside pg_dump's output; a restore without them fails on GRANT."""

    dump = tmp_path / "hope_jobs.dump"
    dump.write_bytes(b"custom-format dump")
    globals_sql = tmp_path / "globals.sql"
    globals_sql.write_text("CREATE ROLE hope_user;")
    archive = tmp_path / "hope.tar.gz"

    backup._bundle(dump, globals_sql, archive)

    with gzip.open(archive, "rb") as handle:
        with tarfile.open(fileobj=handle, mode="r|") as tar:
            assert sorted(member.name for member in tar) == [
                "globals.sql",
                "hope_jobs.dump",
            ]


class _FakeObject:
    def __init__(self, name: str, age_days: int) -> None:
        self.object_name = name
        self.last_modified = datetime.now(UTC) - timedelta(days=age_days)


class _FakeMinio:
    def __init__(self, objects: list[_FakeObject]) -> None:
        self._objects = objects
        self.removed: list[str] = []

    def bucket_exists(self, _bucket: str) -> bool:
        return True

    def list_objects(self, _bucket: str, prefix: str, recursive: bool):  # noqa: ANN201
        del prefix, recursive
        return list(self._objects)

    def remove_objects(self, _bucket: str, objects):  # noqa: ANN001, ANN201
        self.removed.extend(item.name for item in objects)
        return []


@unit
def test_prune_removes_only_archives_past_retention(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = _FakeMinio(
        [
            _FakeObject("postgres/hope-old.tar.gz", age_days=45),
            _FakeObject("postgres/hope-edge.tar.gz", age_days=29),
            _FakeObject("postgres/hope-new.tar.gz", age_days=1),
        ]
    )
    monkeypatch.setattr("hope_job_agent.ops.backup.document_client", lambda: client)

    pruned = backup.prune_old_backups(retention_days=30)

    assert pruned == 1
    assert client.removed == ["postgres/hope-old.tar.gz"]


@unit
def test_prune_is_a_no_op_when_nothing_is_stale(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = _FakeMinio([_FakeObject("postgres/hope-new.tar.gz", age_days=2)])
    monkeypatch.setattr("hope_job_agent.ops.backup.document_client", lambda: client)

    assert backup.prune_old_backups(retention_days=30) == 0
    assert client.removed == []


# --- Full cycle -----------------------------------------------------------


def _client_matches_server() -> bool:
    """pg_dump refuses to dump a server newer than itself."""

    if shutil.which("pg_dump") is None:
        return False
    try:
        output = subprocess.run(
            ["pg_dump", "--version"], capture_output=True, text=True, timeout=10
        ).stdout
    except (OSError, subprocess.SubprocessError):
        return False
    return "18." in output


BACKUP_TEST_MARKER = "pytest-backup-"


@contextmanager
def _seeded_verify_tables(url: Any) -> Iterator[None]:
    """Guarantee one row in each table ``verify_restore`` counts.

    Rows are namespaced by :data:`BACKUP_TEST_MARKER` and removed afterwards so
    the suite leaves the database as it found it.
    """

    import uuid

    from hope_job_agent.db.models import JobPostingRecord
    from hope_job_agent.db.platform_models import User
    from hope_job_agent.db.session import (
        create_db_engine,
        create_session_factory,
        session_scope,
    )

    suffix = uuid.uuid4().hex[:8]
    engine = create_db_engine(
        url.render_as_string(hide_password=False), storage="postgres"
    )
    factory = create_session_factory(engine)
    try:
        with session_scope(factory) as db:
            db.add(
                User(
                    email=f"{BACKUP_TEST_MARKER}{suffix}@example.edu",
                    role="student",
                    status="active",
                )
            )
            db.add(
                JobPostingRecord(
                    source=f"{BACKUP_TEST_MARKER}{suffix}",
                    company_name="Backup Fixture Co",
                    normalized_company_name="backup fixture co",
                    title="Backup Fixture Analyst",
                    normalized_title="backup fixture analyst",
                )
            )
        yield
    finally:
        try:
            with session_scope(factory) as db:
                db.execute(
                    text("DELETE FROM job_postings WHERE source LIKE :p"),
                    {"p": f"{BACKUP_TEST_MARKER}%"},
                )
                db.execute(
                    text("DELETE FROM users WHERE email LIKE :p"),
                    {"p": f"{BACKUP_TEST_MARKER}%"},
                )
        except Exception:  # noqa: BLE001 - cleanup must not mask test outcomes
            pass
        engine.dispose()


@pytest.mark.postgres
@pytest.mark.skipif(
    not _client_matches_server(),
    reason="pg_dump 18 is required (it ships in the application image)",
)
def test_dump_restore_and_verify_round_trip(tmp_path: Path) -> None:
    """A dump that cannot be restored is not a backup.

    This is the assertion the retired n8n workflow claimed to make: it POSTed to
    an endpoint that returned "recorded" without anything ever being dumped.

    Seeds its own rows in every verified table. ``verify_restore`` requires a
    non-zero count -- an empty restore proves nothing -- so borrowing whatever
    another test happened to leave behind made this pass or fail on collection
    order alone, and it fails against a freshly migrated database.
    """

    from sqlalchemy.engine import make_url

    from hope_job_agent.config.database import build_postgres_url

    url = make_url(os.getenv("DATABASE_URL", "").strip() or build_postgres_url())
    dump_path = tmp_path / "hope_jobs.dump"

    with _seeded_verify_tables(url):
        backup._pg_dump(url, dump_path)
        assert dump_path.stat().st_size > 0

        counts = backup.verify_restore(url, dump_path)

    assert set(counts) == set(backup.VERIFY_TABLES)
    assert all(value > 0 for value in counts.values())

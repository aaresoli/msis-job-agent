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
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

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


@pytest.mark.postgres
@pytest.mark.skipif(
    not _client_matches_server(),
    reason="pg_dump 18 is required (it ships in the application image)",
)
def test_dump_restore_and_verify_round_trip(tmp_path: Path) -> None:
    """A dump that cannot be restored is not a backup.

    This is the assertion the retired n8n workflow claimed to make: it POSTed to
    an endpoint that returned "recorded" without anything ever being dumped.
    """

    from sqlalchemy.engine import make_url

    from hope_job_agent.config.database import build_postgres_url

    url = make_url(os.getenv("DATABASE_URL", "").strip() or build_postgres_url())
    dump_path = tmp_path / "hope_jobs.dump"

    backup._pg_dump(url, dump_path)
    assert dump_path.stat().st_size > 0

    counts = backup.verify_restore(url, dump_path)

    assert set(counts) == set(backup.VERIFY_TABLES)
    assert all(value > 0 for value in counts.values())

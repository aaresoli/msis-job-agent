"""Take, upload, and *verify* a PostgreSQL backup.

The platform previously had a ``/backup/verified`` endpoint that returned
``{"status": "recorded"}`` unconditionally, called nightly by a workflow that
was never activated. Nothing was ever dumped.

Two decisions worth stating, because both are the difference between a backup
and the appearance of one:

*Verification means restoring.* Every run loads the archive into a throwaway
database and counts rows in the tables that matter. An archive that uploads
cleanly and cannot be restored is worse than no archive, because it stops anyone
looking for the problem.

*Scope is the system of record.* ``hope_jobs`` plus cluster globals (roles).
``hope_langgraph`` holds checkpoint state that already expires on a TTL and is
rebuilt on the next graph run, and ``hope_phoenix`` holds observability traces;
neither is a system of record, and including them would inflate every archive
with data that regenerates itself.
"""

from __future__ import annotations

import gzip
import hashlib
import logging
import os
import shutil
import subprocess
import tarfile
import tempfile
from contextlib import ExitStack
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from minio.deleteobjects import DeleteObject
from sqlalchemy import create_engine, select, text
from sqlalchemy.engine import URL, make_url
from sqlalchemy.orm import Session

from hope_job_agent.config.database import resolve_database_url
from hope_job_agent.db.platform_models import BackupRun
from hope_job_agent.platform.documents import document_client
from hope_job_agent.platform.settings import get_platform_settings

LOGGER = logging.getLogger(__name__)

# Long enough for a full dump plus a restore on a loaded box; the single-flight
# lock TTL in the calling task must stay above this.
DUMP_TIMEOUT_SECONDS = 3600
# Tables whose row counts are asserted after the verification restore. Chosen
# because an empty one is unambiguously a broken backup rather than a quiet
# deployment.
VERIFY_TABLES = ("job_postings", "users")
OBJECT_PREFIX = "postgres"


class BackupError(RuntimeError):
    pass


def run_backup(db: Session) -> dict[str, Any]:
    """Dump, upload, verify by restore, prune, and record the result."""

    settings = get_platform_settings()
    record = BackupRun(started_at=datetime.now(UTC))
    db.add(record)
    db.flush()
    workdir = Path(tempfile.mkdtemp(prefix="hope-backup-"))
    try:
        url = make_url(resolve_database_url(storage="postgres"))
        dump_path = workdir / "hope_jobs.dump"
        globals_path = workdir / "globals.sql"
        _pg_dump(url, dump_path)
        _pg_dumpall_globals(url, globals_path)

        archive = workdir / _archive_name(record.started_at)
        _bundle(dump_path, globals_path, archive)
        digest, size = _digest(archive)

        object_key = f"{OBJECT_PREFIX}/{archive.name}"
        _upload(archive, object_key)

        counts = verify_restore(url, dump_path)
        pruned = prune_old_backups(settings.backup_retention_days)

        record.finished_at = datetime.now(UTC)
        record.status = "succeeded"
        record.object_key = object_key
        record.size_bytes = size
        record.sha256 = digest
        record.verified = True
        record.verified_tables = counts
        record.pruned_objects = pruned
        return {
            "status": "succeeded",
            "object_key": object_key,
            "size_bytes": size,
            "sha256": digest,
            "verified_tables": counts,
            "pruned_objects": pruned,
        }
    except Exception as exc:
        record.finished_at = datetime.now(UTC)
        record.status = "failed"
        record.verified = False
        record.error_summary = str(exc)[:2000]
        LOGGER.exception("Backup failed")
        raise
    finally:
        # The archive can be tens of gigabytes; leaving it behind fills the
        # container's writable layer within a few nights.
        shutil.rmtree(workdir, ignore_errors=True)


def _archive_name(started_at: datetime) -> str:
    return f"hope-{started_at.strftime('%Y%m%dT%H%M%SZ')}.tar.gz"


def _pg_env(url: URL) -> dict[str, str]:
    """Pass the password through the environment, never argv.

    Command lines are world-readable in ``ps``; ``PGPASSWORD`` is not.
    """

    env = dict(os.environ)
    if url.password:
        env["PGPASSWORD"] = url.password
    return env


def _connection_flags(url: URL) -> list[str]:
    return [
        "--host",
        url.host or "localhost",
        "--port",
        str(url.port or 5432),
        "--username",
        url.username or "postgres",
        "--no-password",
    ]


def _run(command: list[str], url: URL, *, stdout: Path | None = None) -> None:
    with ExitStack() as stack:
        sink = stack.enter_context(stdout.open("wb")) if stdout else None
        result = subprocess.run(
            command,
            env=_pg_env(url),
            stdout=sink,
            stderr=subprocess.PIPE,
            timeout=DUMP_TIMEOUT_SECONDS,
            check=False,
        )
    if result.returncode != 0:
        raise BackupError(
            f"{command[0]} exited {result.returncode}: "
            f"{result.stderr.decode(errors='replace')[:1000]}"
        )


def _pg_dump(url: URL, destination: Path) -> None:
    """Dump the system of record in custom format so ``pg_restore`` can load it."""

    _run(
        [
            "pg_dump",
            *_connection_flags(url),
            "--dbname",
            url.database or "hope_jobs",
            "--format=custom",
            # Restoring into a scratch database owned by a different role must
            # not fail on ownership it cannot grant.
            "--no-owner",
            "--no-privileges",
            "--file",
            str(destination),
        ],
        url,
    )


def _pg_dumpall_globals(url: URL, destination: Path) -> None:
    """Dump cluster roles.

    ``pg_dump`` covers one database's contents but not the roles that own it, so
    a restore onto a fresh cluster without these fails on every GRANT.
    """

    _run(
        [
            "pg_dumpall",
            *_connection_flags(url),
            "--dbname",
            f"postgresql://{url.host or 'localhost'}:{url.port or 5432}/postgres",
            "--globals-only",
            "--no-role-passwords",
        ],
        url,
        stdout=destination,
    )


def _bundle(dump_path: Path, globals_path: Path, archive: Path) -> None:
    """Combine the dump and globals into one gzipped tar."""

    with gzip.open(archive, "wb") as gz:
        with tarfile.open(fileobj=gz, mode="w|") as tar:
            tar.add(dump_path, arcname=dump_path.name)
            tar.add(globals_path, arcname=globals_path.name)


def _digest(path: Path) -> tuple[str, int]:
    """Hash the archive in chunks; it does not fit in memory."""

    sha = hashlib.sha256()
    size = 0
    with path.open("rb") as handle:
        while chunk := handle.read(1024 * 1024):
            sha.update(chunk)
            size += len(chunk)
    return sha.hexdigest(), size


def _upload(archive: Path, object_key: str) -> None:
    settings = get_platform_settings()
    client = document_client()
    if not client.bucket_exists(settings.backup_bucket):
        client.make_bucket(settings.backup_bucket)
    client.fput_object(
        settings.backup_bucket,
        object_key,
        str(archive),
        content_type="application/gzip",
    )


def verify_restore(url: URL, dump_path: Path) -> dict[str, int]:
    """Restore into a throwaway database and count rows; drop it afterwards."""

    scratch = f"hope_verify_{datetime.now(UTC).strftime('%Y%m%d%H%M%S')}"
    admin = create_engine(
        url.set(database="postgres"), isolation_level="AUTOCOMMIT", pool_pre_ping=True
    )
    try:
        with admin.connect() as connection:
            connection.execute(text(f'CREATE DATABASE "{scratch}"'))
        _run(
            [
                "pg_restore",
                *_connection_flags(url),
                "--dbname",
                scratch,
                "--no-owner",
                "--no-privileges",
                str(dump_path),
            ],
            url,
        )
        counts = _count_tables(url.set(database=scratch))
        empty = [name for name, value in counts.items() if value == 0]
        if empty:
            raise BackupError(f"Restored backup has empty tables: {', '.join(empty)}")
        return counts
    finally:
        with admin.connect() as connection:
            # WITH (FORCE) so a lingering pg_restore connection cannot leave a
            # scratch database behind on every nightly run.
            connection.execute(
                text(f'DROP DATABASE IF EXISTS "{scratch}" WITH (FORCE)')
            )
        admin.dispose()


def _count_tables(scratch_url: URL) -> dict[str, int]:
    engine = create_engine(scratch_url, pool_pre_ping=True)
    try:
        with engine.connect() as connection:
            return {
                table: int(
                    connection.execute(
                        text(f"SELECT count(*) FROM {table}")  # noqa: S608
                    ).scalar_one()
                )
                for table in VERIFY_TABLES
            }
    finally:
        engine.dispose()


def prune_old_backups(retention_days: int) -> int:
    """Delete archives past the retention window."""

    settings = get_platform_settings()
    client = document_client()
    if not client.bucket_exists(settings.backup_bucket):
        return 0
    cutoff = datetime.now(UTC) - timedelta(days=retention_days)
    stale = [
        DeleteObject(obj.object_name)
        for obj in client.list_objects(
            settings.backup_bucket, prefix=f"{OBJECT_PREFIX}/", recursive=True
        )
        if obj.object_name and obj.last_modified and obj.last_modified < cutoff
    ]
    if not stale:
        return 0
    errors = list(client.remove_objects(settings.backup_bucket, stale))
    for error in errors:
        LOGGER.error("Failed to prune backup %s: %s", error.name, error.message)
    return len(stale) - len(errors)


def latest_backup(db: Session) -> BackupRun | None:
    """Return the most recent backup attempt, successful or not."""

    return db.scalar(select(BackupRun).order_by(BackupRun.started_at.desc()).limit(1))

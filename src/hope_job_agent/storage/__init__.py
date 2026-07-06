"""Persistence helpers for pipeline runs and job matching outputs."""

from hope_job_agent.storage.base import JobStore, JobStoreError, create_job_store
from hope_job_agent.storage.memory_store import MemoryJobStore
from hope_job_agent.storage.postgres_store import (
    PostgresJobStore,
    PostgresJobStoreError,
)
from hope_job_agent.storage.sqlite_store import (
    DEFAULT_DATABASE_PATH,
    SQLiteJobStore,
    SQLiteJobStoreError,
    content_signature,
    resolve_sqlite_database,
    student_key,
)

__all__ = [
    "DEFAULT_DATABASE_PATH",
    "JobStore",
    "JobStoreError",
    "MemoryJobStore",
    "PostgresJobStore",
    "PostgresJobStoreError",
    "SQLiteJobStore",
    "SQLiteJobStoreError",
    "content_signature",
    "create_job_store",
    "resolve_sqlite_database",
    "student_key",
]

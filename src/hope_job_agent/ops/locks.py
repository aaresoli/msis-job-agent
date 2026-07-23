"""Single-flight guard for scheduled work.

The HTTP path dedupes with ``IdempotencyRecord`` keyed on a caller-supplied
header. Beat has no such header, and the operator-facing ``/internal/v1`` routes
remain available, so a manual trigger can land on top of a scheduled one. A full
ATS sweep takes tens of minutes; two overlapping sweeps double the request rate
against employer boards, which is exactly what the rate limiting in the source
adapters exists to prevent.
"""

from __future__ import annotations

import logging
import os
import socket
from collections.abc import Iterator
from contextlib import contextmanager
from functools import lru_cache

import redis

from hope_job_agent.platform.settings import get_platform_settings

LOGGER = logging.getLogger(__name__)

KEY_PREFIX = "hope:single-flight:"


class AlreadyRunning(RuntimeError):
    """Raised when the lock is held by another run."""


@lru_cache
def _client() -> redis.Redis:
    return redis.Redis.from_url(get_platform_settings().redis_url)


def _owner() -> str:
    return f"{socket.gethostname()}:{os.getpid()}"


@contextmanager
def single_flight(key: str, ttl_seconds: int) -> Iterator[None]:
    """Hold an exclusive lock on ``key`` or raise :class:`AlreadyRunning`.

    ``ttl_seconds`` must exceed the task's own time limit: the TTL is what
    releases the lock when a worker is killed mid-run, and a TTL shorter than
    the work it guards would let a second run start while the first is alive.

    Release is owner-checked, so a run that overran its TTL cannot delete the
    lock a later run is holding.
    """

    client = _client()
    full_key = f"{KEY_PREFIX}{key}"
    owner = _owner()
    if not client.set(full_key, owner, nx=True, ex=ttl_seconds):
        raise AlreadyRunning(f"{key} is already running")
    try:
        yield
    finally:
        # Compare-and-delete: a plain DELETE would drop a *different* run's
        # lock if this one had already expired.
        client.eval(
            "if redis.call('get', KEYS[1]) == ARGV[1] "
            "then return redis.call('del', KEYS[1]) else return 0 end",
            1,
            full_key,
            owner,
        )

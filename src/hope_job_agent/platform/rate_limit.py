"""Privacy-preserving Redis rate limits with an outage-safe local fallback."""

from __future__ import annotations

import hashlib
import threading
import time
from functools import lru_cache

from redis import ConnectionPool, Redis
from redis.commands.core import Script
from redis.exceptions import RedisError

# INCR and EXPIRE must land together. Issued separately, a crash or a dropped
# connection between them leaves a counter with no TTL, which never decays and
# locks that identity out permanently.
_INCREMENT_WITH_TTL = """
local current = redis.call('INCR', KEYS[1])
if current == 1 then
  redis.call('EXPIRE', KEYS[1], ARGV[1])
end
return current
"""

_lock = threading.Lock()
_fallback: dict[str, tuple[int, float]] = {}

# Keeps the process-local fallback from growing without bound during a long
# Redis outage; entries are tiny, so a generous ceiling is fine.
_FALLBACK_MAX_ENTRIES = 10_000


@lru_cache(maxsize=8)
def _script(redis_url: str) -> Script:
    """Return the registered limiter script for ``redis_url``.

    Cached so each URL keeps one connection pool for the process rather than
    opening a fresh connection per request.
    """

    pool = ConnectionPool.from_url(
        redis_url,
        socket_connect_timeout=0.2,
        socket_timeout=0.2,
    )
    return Redis(connection_pool=pool).register_script(_INCREMENT_WITH_TTL)


def allow_request(
    *, bucket: str, identity: str, limit: int, window_seconds: int, redis_url: str
) -> bool:
    digest = hashlib.sha256(identity.casefold().encode()).hexdigest()
    key = f"hope:rate:{bucket}:{digest}"
    try:
        count = int(_script(redis_url)(keys=[key], args=[window_seconds]))
        return count <= limit
    except RedisError:
        return _allow_request_locally(key, limit, window_seconds)


def _allow_request_locally(key: str, limit: int, window_seconds: int) -> bool:
    """Approximate the limit in-process while Redis is unreachable.

    Per-process rather than global, so a multi-worker deployment enforces a
    looser effective limit during an outage. That is the intended trade: the
    limiter degrades toward availability, not toward locking students out.
    """

    now = time.monotonic()
    with _lock:
        if len(_fallback) >= _FALLBACK_MAX_ENTRIES:
            for expired in [k for k, (_, exp) in _fallback.items() if now >= exp]:
                del _fallback[expired]
        count, expires = _fallback.get(key, (0, now + window_seconds))
        if now >= expires:
            count, expires = 0, now + window_seconds
        count += 1
        _fallback[key] = (count, expires)
        return count <= limit

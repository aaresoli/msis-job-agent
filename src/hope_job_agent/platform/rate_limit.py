"""Privacy-preserving Redis rate limits with an outage-safe local fallback."""

from __future__ import annotations

import hashlib
import threading
import time
from typing import cast

from redis import Redis
from redis.exceptions import RedisError

_lock = threading.Lock()
_fallback: dict[str, tuple[int, float]] = {}


def allow_request(
    *, bucket: str, identity: str, limit: int, window_seconds: int, redis_url: str
) -> bool:
    digest = hashlib.sha256(identity.casefold().encode()).hexdigest()
    key = f"hope:rate:{bucket}:{digest}"
    try:
        client = Redis.from_url(
            redis_url, socket_connect_timeout=0.2, socket_timeout=0.2
        )
        count = int(cast(int, client.incr(key)))
        if count == 1:
            client.expire(key, window_seconds)
        return count <= limit
    except RedisError:
        now = time.monotonic()
        with _lock:
            count, expires = _fallback.get(key, (0, now + window_seconds))
            if now >= expires:
                count, expires = 0, now + window_seconds
            count += 1
            _fallback[key] = (count, expires)
            return count <= limit

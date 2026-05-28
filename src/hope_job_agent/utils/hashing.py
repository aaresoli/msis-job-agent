"""Stable hashing helpers for future IDs and deduplication."""

from hashlib import sha256


def stable_hash(value: str) -> str:
    """Return a stable SHA-256 hash for a text value."""

    return sha256(value.strip().lower().encode("utf-8")).hexdigest()

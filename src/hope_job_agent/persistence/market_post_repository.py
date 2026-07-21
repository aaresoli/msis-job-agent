"""Upsert access for LinkedIn hiring posts (``market_posts``).

The Apify webhook path (``api/internal.py``) inlines a minimal insert; this
repository is the reusable equivalent for the REST *pull* source
(:mod:`hope_job_agent.sources.apify_linkedin_posts`). Posts dedup on the table's
``(source, external_id)`` unique constraint, and re-fetches of an unchanged post
(same ``content_hash``) are no-ops so re-running an ingest is idempotent.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from hope_job_agent.db.platform_models import MarketPost


@dataclass(frozen=True)
class MarketPostUpsertSummary:
    """Per-run accounting for a market-post upsert."""

    inserted: int = 0
    updated: int = 0
    unchanged: int = 0

    @property
    def total(self) -> int:
        return self.inserted + self.updated + self.unchanged


class MarketPostRepository:
    """Idempotent upsert of normalized market posts into ``market_posts``."""

    def __init__(self, session: Session) -> None:
        self.session = session

    def upsert_many(self, posts: list[dict[str, Any]]) -> MarketPostUpsertSummary:
        """Insert new posts, update changed ones, and skip unchanged ones."""

        inserted = updated = unchanged = 0
        for post in posts:
            outcome = self._upsert_one(post)
            if outcome == "inserted":
                inserted += 1
            elif outcome == "updated":
                updated += 1
            else:
                unchanged += 1
        self.session.flush()
        return MarketPostUpsertSummary(
            inserted=inserted,
            updated=updated,
            unchanged=unchanged,
        )

    def _upsert_one(self, post: dict[str, Any]) -> str:
        fields = _record_fields(post)
        existing = self.session.scalar(
            select(MarketPost).where(
                MarketPost.source == fields["source"],
                MarketPost.external_id == fields["external_id"],
            )
        )
        if existing is None:
            self.session.add(MarketPost(**fields))
            return "inserted"

        if existing.content_hash == fields["content_hash"]:
            return "unchanged"

        existing.content = fields["content"]
        existing.content_hash = fields["content_hash"]
        existing.author_name = fields["author_name"]
        existing.company_name = fields["company_name"]
        existing.source_url = fields["source_url"]
        existing.published_at = fields["published_at"]
        existing.raw_metadata = fields["raw_metadata"]
        return "updated"


def _record_fields(post: dict[str, Any]) -> dict[str, Any]:
    """Project a normalized post dict onto the ``MarketPost`` column set."""

    return {
        "source": post["source"],
        "external_id": post["external_id"],
        "author_name": post.get("author_name"),
        "company_name": post.get("company_name"),
        "content": post["content"],
        "source_url": post["source_url"],
        "published_at": _coerce_datetime(post.get("published_at")),
        "content_hash": post["content_hash"],
        "raw_metadata": post.get("raw_metadata"),
    }


def _coerce_datetime(value: Any) -> datetime | None:
    if value is None or isinstance(value, datetime):
        return value
    text = str(value).strip()
    if not text:
        return None
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None

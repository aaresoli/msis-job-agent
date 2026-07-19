"""Disabled Apify normalization contracts for jobs and hiring-intelligence posts."""

from __future__ import annotations

import hashlib
from datetime import UTC, datetime
from typing import Any, Literal

from pydantic import BaseModel, Field, SecretStr

from hope_job_agent.models.job import JobPosting
from hope_job_agent.sources.contracts import SourceBatch, SourceDisabledError


class ApifyConfig(BaseModel):
    enabled: bool = False
    token: SecretStr = SecretStr("")
    jobs_actor_id: str = ""
    posts_actor_id: str = ""
    mode: Literal["webhook", "poll"] = "webhook"
    page_size: int = Field(default=100, ge=1, le=1000)
    monthly_spend_limit_usd: float = Field(default=25.0, ge=0)
    source_approval_id: str = ""


class ApifyConnector:
    source_name = "apify_linkedin"

    def __init__(self, config: ApifyConfig) -> None:
        self.config = config
        self.enabled = config.enabled and bool(config.source_approval_id)

    def fetch_page(
        self,
        *,
        cursor: str | None = None,
        watermark: datetime | None = None,
        limit: int = 100,
    ) -> SourceBatch[dict[str, Any]]:
        del cursor, watermark, limit
        if not self.enabled:
            raise SourceDisabledError(
                "Apify LinkedIn collection is disabled pending a documented "
                "source approval."
            )
        raise SourceDisabledError(
            "Apify actor and dataset mapping has not been supplied; no network "
            "request was made."
        )


def normalize_apify_job(item: dict[str, Any], actor_run_id: str) -> JobPosting:
    external_id = str(item.get("id") or item.get("jobId") or item.get("url") or "")
    return JobPosting(
        source="apify_linkedin_jobs",
        source_job_id=external_id,
        title=str(item.get("title") or item.get("jobTitle") or ""),
        company=str(item.get("company") or item.get("companyName") or ""),
        location=str(item.get("location") or "Not specified"),
        description=str(item.get("description") or item.get("text") or ""),
        url=str(item.get("url") or item.get("jobUrl") or ""),
        posted_date=item.get("postedDate") or item.get("date"),
        apply_url=item.get("applyUrl"),
        source_detail="apify_linkedin",
        retrieved_at=datetime.now(UTC),
        raw_metadata={"actor_run_id": actor_run_id, "payload": item},
    )


def normalize_apify_post(item: dict[str, Any], actor_run_id: str) -> dict[str, Any]:
    content = str(item.get("text") or item.get("content") or "")
    source_url = str(item.get("url") or item.get("postUrl") or "")
    external_id = str(
        item.get("id") or source_url or hashlib.sha256(content.encode()).hexdigest()
    )
    return {
        "source": "apify_linkedin_posts",
        "external_id": external_id,
        "author_name": item.get("authorName") or item.get("author"),
        "company_name": item.get("companyName"),
        "content": content,
        "source_url": source_url,
        "published_at": item.get("publishedAt") or item.get("date"),
        "content_hash": hashlib.sha256(content.encode()).hexdigest(),
        "raw_metadata": {"actor_run_id": actor_run_id, "payload": item},
    }

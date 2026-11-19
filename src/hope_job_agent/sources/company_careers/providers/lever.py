"""Lever public postings adapter.

Uses the public Lever postings JSON endpoint:
``https://api.lever.co/v0/postings/{site}?mode=json`` which returns an array of
postings including plain-text descriptions, categories, and hosted URLs.
"""

from __future__ import annotations

from typing import Any

from hope_job_agent.sources.company_careers.config import CompanyTarget, FetchPolicy
from hope_job_agent.sources.company_careers.http import HttpClient
from hope_job_agent.sources.company_careers.providers.base import (
    BaseProvider,
    ProviderError,
    RawJob,
    clean_html,
    parse_date,
)

POSTINGS_API_BASE = "https://api.lever.co/v0/postings"


class LeverProvider(BaseProvider):
    name = "lever"

    def primary_endpoint(self, target: CompanyTarget) -> str:
        site = self._require(target.ats_slug, "ats_slug", target)
        return f"{POSTINGS_API_BASE}/{site}?mode=json"

    def fetch(
        self,
        client: HttpClient,
        target: CompanyTarget,
        policy: FetchPolicy,
    ) -> list[RawJob]:
        url = self.primary_endpoint(target)
        payload = client.get_json(url)

        if not isinstance(payload, list):
            raise ProviderError(
                f"Lever response for '{target.company_name}' was not a postings array"
            )

        raw_jobs: list[RawJob] = []
        for entry in payload[: policy.max_jobs_per_company]:
            if not isinstance(entry, dict):
                continue
            raw_jobs.append(self._to_raw_job(entry, target))
        return raw_jobs

    def _to_raw_job(self, entry: dict[str, Any], target: CompanyTarget) -> RawJob:
        categories = entry.get("categories") or {}
        if not isinstance(categories, dict):
            categories = {}

        description = entry.get("descriptionPlain") or clean_html(
            entry.get("description")
        )
        lists_text = _flatten_lists(entry.get("lists"))
        if lists_text:
            description = f"{description}\n{lists_text}".strip()
        additional = entry.get("additionalPlain")
        if additional:
            description = f"{description}\n{additional}".strip()

        hosted_url = str(entry.get("hostedUrl") or "").strip()
        apply_url = str(entry.get("applyUrl") or "").strip() or hosted_url

        return RawJob(
            source_job_id=str(entry.get("id") or ""),
            title=str(entry.get("text") or "").strip(),
            company=target.company_name,
            url=hosted_url,
            apply_url=apply_url,
            location=categories.get("location"),
            description=description,
            employment_type=categories.get("commitment"),
            department=categories.get("department") or categories.get("team"),
            location_type=entry.get("workplaceType"),
            posted_date=parse_date(entry.get("createdAt")),
            raw_payload=entry,
        )


def _flatten_lists(value: Any) -> str:
    if not isinstance(value, list):
        return ""
    parts: list[str] = []
    for item in value:
        if not isinstance(item, dict):
            continue
        text = item.get("text")
        content = clean_html(item.get("content"))
        if text:
            parts.append(str(text))
        if content:
            parts.append(content)
    return " ".join(parts).strip()

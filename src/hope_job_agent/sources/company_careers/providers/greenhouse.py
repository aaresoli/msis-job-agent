"""Greenhouse public job-board adapter.

Uses the public Greenhouse Boards API:
``https://boards-api.greenhouse.io/v1/boards/{board_token}/jobs?content=true``
which returns postings with embedded (HTML) content, so no per-job detail
request is required.
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

BOARDS_API_BASE = "https://boards-api.greenhouse.io/v1/boards"


class GreenhouseProvider(BaseProvider):
    name = "greenhouse"

    def primary_endpoint(self, target: CompanyTarget) -> str:
        token = self._require(target.ats_slug, "ats_slug", target)
        return f"{BOARDS_API_BASE}/{token}/jobs?content=true"

    def fetch(
        self,
        client: HttpClient,
        target: CompanyTarget,
        policy: FetchPolicy,
    ) -> list[RawJob]:
        url = self.primary_endpoint(target)
        # HttpError (including blocked/403) intentionally propagates so the
        # orchestrator can disable a source that blocks the crawler.
        payload = client.get_json(url)

        jobs_payload = payload.get("jobs") if isinstance(payload, dict) else None
        if not isinstance(jobs_payload, list):
            raise ProviderError(
                f"Greenhouse response for '{target.company_name}' had no jobs array"
            )

        raw_jobs: list[RawJob] = []
        for entry in jobs_payload[: policy.max_jobs_per_company]:
            if not isinstance(entry, dict):
                continue
            raw_jobs.append(self._to_raw_job(entry, target))
        return raw_jobs

    def _to_raw_job(self, entry: dict[str, Any], target: CompanyTarget) -> RawJob:
        location = entry.get("location") or {}
        location_name = location.get("name") if isinstance(location, dict) else None
        departments = entry.get("departments") or []
        department = None
        if departments and isinstance(departments[0], dict):
            department = departments[0].get("name")

        location_type = None
        if location_name and "remote" in location_name.casefold():
            location_type = "remote"

        absolute_url = str(entry.get("absolute_url") or "").strip()
        return RawJob(
            source_job_id=str(entry.get("id") or ""),
            title=str(entry.get("title") or "").strip(),
            company=target.company_name,
            url=absolute_url,
            apply_url=absolute_url,
            location=location_name,
            description=clean_html(entry.get("content")),
            department=department,
            location_type=location_type,
            posted_date=parse_date(
                entry.get("updated_at") or entry.get("first_published")
            ),
            raw_payload=entry,
        )

"""Ashby public job-board adapter.

Uses the public Ashby posting API:
``https://api.ashbyhq.com/posting-api/job-board/{board_name}?includeCompensation=true``
which returns published postings with descriptions, locations, and apply URLs.
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

JOB_BOARD_API_BASE = "https://api.ashbyhq.com/posting-api/job-board"


class AshbyProvider(BaseProvider):
    name = "ashby"

    def primary_endpoint(self, target: CompanyTarget) -> str:
        board = self._require(target.ats_slug, "ats_slug", target)
        return f"{JOB_BOARD_API_BASE}/{board}?includeCompensation=true"

    def fetch(
        self,
        client: HttpClient,
        target: CompanyTarget,
        policy: FetchPolicy,
    ) -> list[RawJob]:
        url = self.primary_endpoint(target)
        payload = client.get_json(url)

        jobs_payload = payload.get("jobs") if isinstance(payload, dict) else None
        if not isinstance(jobs_payload, list):
            raise ProviderError(
                f"Ashby response for '{target.company_name}' had no jobs array"
            )

        raw_jobs: list[RawJob] = []
        for entry in jobs_payload[: policy.max_jobs_per_company]:
            if not isinstance(entry, dict):
                continue
            raw_jobs.append(self._to_raw_job(entry, target))
        return raw_jobs

    def _to_raw_job(self, entry: dict[str, Any], target: CompanyTarget) -> RawJob:
        description = entry.get("descriptionPlain") or clean_html(
            entry.get("descriptionHtml")
        )
        job_url = str(entry.get("jobUrl") or "").strip()
        apply_url = str(entry.get("applyUrl") or "").strip() or job_url
        department = entry.get("department") or entry.get("team")

        location_type = None
        if entry.get("isRemote") is True:
            location_type = "remote"

        return RawJob(
            source_job_id=str(entry.get("id") or entry.get("jobId") or ""),
            title=str(entry.get("title") or "").strip(),
            company=target.company_name,
            url=job_url,
            apply_url=apply_url,
            location=entry.get("location"),
            description=description,
            employment_type=entry.get("employmentType"),
            department=department,
            location_type=location_type,
            compensation=_compensation(entry),
            posted_date=parse_date(entry.get("publishedAt") or entry.get("updatedAt")),
            raw_payload=entry,
        )


def _compensation(entry: dict[str, Any]) -> str | None:
    summary = entry.get("compensationTierSummary")
    if isinstance(summary, str) and summary.strip():
        return summary.strip()
    compensation = entry.get("compensation")
    if isinstance(compensation, dict):
        summary = compensation.get("compensationTierSummary")
        if isinstance(summary, str) and summary.strip():
            return summary.strip()
    return None

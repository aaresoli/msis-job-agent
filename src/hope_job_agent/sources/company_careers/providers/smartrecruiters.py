"""SmartRecruiters public postings adapter.

Uses the public company postings API:
``https://api.smartrecruiters.com/v1/companies/{companyId}/postings`` (paginated)
and, when ``fetch_descriptions`` is enabled, the per-posting detail endpoint
``.../postings/{id}`` for the full job description and qualifications.
"""

from __future__ import annotations

from typing import Any

from hope_job_agent.sources.company_careers.config import CompanyTarget, FetchPolicy
from hope_job_agent.sources.company_careers.http import HttpClient, HttpError
from hope_job_agent.sources.company_careers.providers.base import (
    BaseProvider,
    RawJob,
    clean_html,
    parse_date,
)

POSTINGS_API_BASE = "https://api.smartrecruiters.com/v1/companies"
CAREERS_BASE = "https://jobs.smartrecruiters.com"
PAGE_SIZE = 100


class SmartRecruitersProvider(BaseProvider):
    name = "smartrecruiters"

    def primary_endpoint(self, target: CompanyTarget) -> str:
        company_id = self._require(target.ats_slug, "ats_slug", target)
        return f"{POSTINGS_API_BASE}/{company_id}/postings?limit={PAGE_SIZE}&offset=0"

    def fetch(
        self,
        client: HttpClient,
        target: CompanyTarget,
        policy: FetchPolicy,
    ) -> list[RawJob]:
        company_id = self._require(target.ats_slug, "ats_slug", target)
        raw_jobs: list[RawJob] = []
        offset = 0
        while len(raw_jobs) < policy.max_jobs_per_company:
            url = (
                f"{POSTINGS_API_BASE}/{company_id}/postings"
                f"?limit={PAGE_SIZE}&offset={offset}"
            )
            payload = client.get_json(url)

            content = payload.get("content") if isinstance(payload, dict) else None
            if not isinstance(content, list) or not content:
                break

            for entry in content:
                if not isinstance(entry, dict):
                    continue
                raw_jobs.append(
                    self._to_raw_job(entry, target, company_id, client, policy)
                )
                if len(raw_jobs) >= policy.max_jobs_per_company:
                    break

            offset += PAGE_SIZE
            total_found = payload.get("totalFound", 0)
            if not isinstance(total_found, int) or offset >= total_found:
                break
        return raw_jobs

    def _to_raw_job(
        self,
        entry: dict[str, Any],
        target: CompanyTarget,
        company_id: str,
        client: HttpClient,
        policy: FetchPolicy,
    ) -> RawJob:
        posting_id = str(entry.get("id") or "")
        location = entry.get("location") or {}
        if not isinstance(location, dict):
            location = {}
        location_text = location.get("fullLocation") or _compose_location(location)

        location_type = None
        if location.get("remote"):
            location_type = "remote"
        elif location.get("hybrid"):
            location_type = "hybrid"

        employment_type = _label(entry.get("typeOfEmployment"))
        department = _label(entry.get("department")) or _label(entry.get("function"))

        description = ""
        compensation = None
        if policy.fetch_descriptions and posting_id:
            description, compensation = self._fetch_detail(
                client, company_id, posting_id
            )

        careers_url = f"{CAREERS_BASE}/{company_id}/{posting_id}"
        return RawJob(
            source_job_id=posting_id,
            title=str(entry.get("name") or "").strip(),
            company=target.company_name,
            url=careers_url,
            apply_url=careers_url,
            location=location_text,
            description=description,
            employment_type=employment_type,
            department=department,
            location_type=location_type,
            compensation=compensation,
            posted_date=parse_date(entry.get("releasedDate")),
            raw_payload=entry,
        )

    def _fetch_detail(
        self,
        client: HttpClient,
        company_id: str,
        posting_id: str,
    ) -> tuple[str, str | None]:
        detail_url = f"{POSTINGS_API_BASE}/{company_id}/postings/{posting_id}"
        try:
            detail = client.get_json(detail_url)
        except HttpError:
            return "", None
        if not isinstance(detail, dict):
            return "", None

        job_ad = detail.get("jobAd") or {}
        sections = job_ad.get("sections") if isinstance(job_ad, dict) else {}
        sections = sections if isinstance(sections, dict) else {}
        parts = [
            _section_text(sections.get("jobDescription")),
            _section_text(sections.get("qualifications")),
            _section_text(sections.get("additionalInformation")),
        ]
        description = clean_html(" ".join(part for part in parts if part))
        return description, None


def _section_text(section: Any) -> str:
    if isinstance(section, dict):
        return str(section.get("text") or "")
    return ""


def _compose_location(location: dict[str, Any]) -> str | None:
    city = location.get("city")
    region = location.get("region")
    country = location.get("country")
    parts = [part for part in (city, region, country) if part]
    return ", ".join(str(part) for part in parts) or None


def _label(value: Any) -> str | None:
    if isinstance(value, dict):
        label = value.get("label")
        if label:
            return str(label)
    return None

"""Workday public career-site adapter.

Workday tenants expose a public ``/wday/cxs/{tenant}/{site}/jobs`` endpoint that
accepts a small JSON POST body and returns a paginated list of postings. This
adapter uses only that public endpoint discovered from a company's configured
career site. It does NOT reverse-engineer private authenticated APIs, and keeps
request volume low.

Because Workday tenants/sites vary per employer and can change, Workday-backed
companies should be enabled one at a time after the tenant/site/host are
verified. Brittle companies should be left ``enabled: false`` rather than
shipping flaky behavior.
"""

from __future__ import annotations

from typing import Any

from hope_job_agent.sources.company_careers.config import CompanyTarget, FetchPolicy
from hope_job_agent.sources.company_careers.http import (
    BLOCKED_STATUS_CODES as _BLOCKED_STATUS_CODES,
)
from hope_job_agent.sources.company_careers.http import (
    HttpClient,
    HttpError,
)
from hope_job_agent.sources.company_careers.providers.base import (
    BaseProvider,
    ProviderError,
    RawJob,
    clean_html,
    parse_date,
)

PAGE_SIZE = 20


class WorkdayProvider(BaseProvider):
    name = "workday"

    def primary_endpoint(self, target: CompanyTarget) -> str:
        host = self._require(target.host, "host", target)
        tenant = self._require(target.tenant, "tenant", target)
        site = self._require(target.site, "site", target)
        return f"https://{host}/wday/cxs/{tenant}/{site}/jobs"

    def fetch(
        self,
        client: HttpClient,
        target: CompanyTarget,
        policy: FetchPolicy,
    ) -> list[RawJob]:
        host = self._require(target.host, "host", target)
        site = self._require(target.site, "site", target)
        endpoint = self.primary_endpoint(target)

        raw_jobs: list[RawJob] = []
        offset = 0
        while len(raw_jobs) < policy.max_jobs_per_company:
            body = {
                "appliedFacets": {},
                "limit": PAGE_SIZE,
                "offset": offset,
                "searchText": "",
            }
            response = client.post_json(endpoint, body)
            if response.status_code in _BLOCKED_STATUS_CODES:
                raise HttpError(
                    f"Access blocked ({response.status_code}) for {endpoint}",
                    status_code=response.status_code,
                    blocked=True,
                )
            if response.status_code >= 400:
                raise ProviderError(
                    f"Workday returned HTTP {response.status_code} for "
                    f"'{target.company_name}'"
                )
            payload = response.json()
            postings = payload.get("jobPostings") if isinstance(payload, dict) else None
            if not isinstance(postings, list) or not postings:
                break

            for entry in postings:
                if not isinstance(entry, dict):
                    continue
                raw_jobs.append(
                    self._to_raw_job(entry, target, host, site, client, policy)
                )
                if len(raw_jobs) >= policy.max_jobs_per_company:
                    break

            offset += PAGE_SIZE
            total = payload.get("total", 0)
            if not isinstance(total, int) or offset >= total:
                break
        return raw_jobs

    def _to_raw_job(
        self,
        entry: dict[str, Any],
        target: CompanyTarget,
        host: str,
        site: str,
        client: HttpClient,
        policy: FetchPolicy,
    ) -> RawJob:
        external_path = str(entry.get("externalPath") or "").strip()
        bullet_fields = entry.get("bulletFields") or []
        source_job_id = ""
        if isinstance(bullet_fields, list) and bullet_fields:
            source_job_id = str(bullet_fields[0])
        if not source_job_id and external_path:
            source_job_id = external_path.rstrip("/").rsplit("/", 1)[-1]

        careers_url = f"https://{host}/{site}{external_path}"
        description = ""
        posted_date = None
        if policy.fetch_descriptions and external_path:
            description, posted_date = self._fetch_detail(
                client, host, target, external_path
            )

        return RawJob(
            source_job_id=source_job_id or careers_url,
            title=str(entry.get("title") or "").strip(),
            company=target.company_name,
            url=careers_url,
            apply_url=careers_url,
            location=entry.get("locationsText"),
            description=description,
            posted_date=posted_date,
            raw_payload=entry,
        )

    def _fetch_detail(
        self,
        client: HttpClient,
        host: str,
        target: CompanyTarget,
        external_path: str,
    ) -> tuple[str, Any]:
        tenant = target.tenant or ""
        site = target.site or ""
        detail_url = f"https://{host}/wday/cxs/{tenant}/{site}{external_path}"
        try:
            detail = client.get_json(detail_url)
        except HttpError:
            return "", None
        info = detail.get("jobPostingInfo") if isinstance(detail, dict) else None
        if not isinstance(info, dict):
            return "", None
        description = clean_html(info.get("jobDescription"))
        posted_date = parse_date(info.get("startDate") or info.get("postedOn"))
        return description, posted_date

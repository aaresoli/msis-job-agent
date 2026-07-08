"""Oracle Recruiting Cloud (Candidate Experience) public adapter.

Oracle Fusion HCM tenants expose an unauthenticated Candidate Experience REST
API under ``/hcmRestApi/resources/latest/recruitingCEJobRequisitions`` — the
same endpoint the public career site itself calls (documented in Oracle's
"REST API for Recruiting" guide). This adapter uses only that public list
endpoint plus the matching ``recruitingCEJobRequisitionDetails`` detail
endpoint, keeps request volume low, and performs no authentication.

Config mapping for ``ats_provider: oraclecloud``:

* ``host`` -> the tenant's Fusion host, e.g. ``eeho.fa.us2.oraclecloud.com``.
* ``site`` -> the Candidate Experience site number, e.g. ``CX_1001``.

Because hosts and site numbers vary per employer, Oracle-backed companies must
be verified (one live list request) before being enabled.
"""

from __future__ import annotations

from typing import Any
from urllib.parse import quote

from hope_job_agent.sources.company_careers.config import CompanyTarget, FetchPolicy
from hope_job_agent.sources.company_careers.http import HttpClient, HttpError
from hope_job_agent.sources.company_careers.providers.base import (
    BaseProvider,
    ProviderError,
    RawJob,
    clean_html,
    parse_date,
)

PAGE_SIZE = 25


class OracleCloudProvider(BaseProvider):
    name = "oraclecloud"

    def primary_endpoint(self, target: CompanyTarget) -> str:
        return self._list_url(target, limit=PAGE_SIZE, offset=0)

    def fetch(
        self,
        client: HttpClient,
        target: CompanyTarget,
        policy: FetchPolicy,
    ) -> list[RawJob]:
        raw_jobs: list[RawJob] = []
        offset = 0
        while len(raw_jobs) < policy.max_jobs_per_company:
            url = self._list_url(target, limit=PAGE_SIZE, offset=offset)
            payload = client.get_json(url)

            item = _first_item(payload)
            if item is None:
                break
            requisitions = item.get("requisitionList")
            if not isinstance(requisitions, list) or not requisitions:
                break

            for entry in requisitions:
                if not isinstance(entry, dict):
                    continue
                raw_jobs.append(self._to_raw_job(entry, target, client, policy))
                if len(raw_jobs) >= policy.max_jobs_per_company:
                    break

            offset += PAGE_SIZE
            total = item.get("TotalJobsCount", 0)
            if not isinstance(total, int) or offset >= total:
                break
        return raw_jobs

    def _list_url(self, target: CompanyTarget, *, limit: int, offset: int) -> str:
        host = self._require(target.host, "host", target)
        site = self._require(target.site, "site", target)
        if "oraclecloud.com" not in host:
            raise ProviderError(
                f"oraclecloud adapter expects an *.oraclecloud.com host for "
                f"'{target.company_name}' (got '{host}')"
            )
        finder = (
            f"findReqs;siteNumber={site},limit={limit},offset={offset},"
            "sortBy=POSTING_DATES_DESC"
        )
        # Without expand=requisitionList the API returns only search metadata.
        return (
            f"https://{host}/hcmRestApi/resources/latest/recruitingCEJobRequisitions"
            f"?onlyData=true&expand=requisitionList.secondaryLocations"
            f"&finder={finder}"
        )

    def _to_raw_job(
        self,
        entry: dict[str, Any],
        target: CompanyTarget,
        client: HttpClient,
        policy: FetchPolicy,
    ) -> RawJob:
        host = self._require(target.host, "host", target)
        site = self._require(target.site, "site", target)
        requisition_id = str(entry.get("Id") or "").strip()
        careers_url = (
            f"https://{host}/hcmUI/CandidateExperience/en/sites/{site}"
            f"/job/{requisition_id}"
        )

        description = clean_html(
            entry.get("ShortDescriptionStr") or entry.get("ExternalDescriptionStr")
        )
        if policy.fetch_descriptions and requisition_id:
            detail = self._fetch_detail(client, host, site, requisition_id)
            if detail:
                description = detail

        location = entry.get("PrimaryLocation")
        workplace = str(entry.get("WorkplaceType") or "").strip().casefold() or None
        if workplace not in {None, "remote", "hybrid", "on-site", "onsite"}:
            workplace = None

        return RawJob(
            source_job_id=requisition_id or careers_url,
            title=str(entry.get("Title") or "").strip(),
            company=target.company_name,
            url=careers_url,
            apply_url=careers_url,
            location=str(location) if location else None,
            description=description,
            location_type=workplace,
            posted_date=parse_date(entry.get("PostedDate")),
            raw_payload=entry,
        )

    def _fetch_detail(
        self,
        client: HttpClient,
        host: str,
        site: str,
        requisition_id: str,
    ) -> str:
        quoted_id = quote(f'"{requisition_id}"', safe="")
        detail_url = (
            f"https://{host}/hcmRestApi/resources/latest/"
            "recruitingCEJobRequisitionDetails"
            f"?onlyData=true&expand=all"
            f"&finder=ById;siteNumber={site},Id={quoted_id}"
        )
        try:
            payload = client.get_json(detail_url)
        except HttpError:
            return ""
        item = _first_item(payload)
        if item is None:
            return ""
        return clean_html(
            item.get("ExternalDescriptionStr")
            or item.get("ExternalQualificationsStr")
            or item.get("ShortDescriptionStr")
        )


def _first_item(payload: Any) -> dict[str, Any] | None:
    if not isinstance(payload, dict):
        return None
    items = payload.get("items")
    if not isinstance(items, list) or not items:
        return None
    first = items[0]
    return first if isinstance(first, dict) else None

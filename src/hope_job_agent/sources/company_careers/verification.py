"""Low-volume endpoint verification for configured company targets.

Used by ``scripts/ats_refresh_endpoints.py`` (and tests) to confirm that an
enabled company's public ATS endpoint still responds, with exactly ONE small
request per company (limit=1 wherever the API supports it). It never mutates
config — refresh reports flag drift for deliberate follow-up edits.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from hope_job_agent.sources.company_careers.config import CompanyTarget
from hope_job_agent.sources.company_careers.http import HttpClient, HttpError

_GREENHOUSE = "https://boards-api.greenhouse.io/v1/boards/{slug}/jobs"
_LEVER = "https://api.lever.co/v0/postings/{slug}?mode=json&limit=1"
_ASHBY = "https://api.ashbyhq.com/posting-api/job-board/{slug}"
_SMARTRECRUITERS = (
    "https://api.smartrecruiters.com/v1/companies/{slug}/postings?limit=1"
)


@dataclass(frozen=True)
class VerifyOutcome:
    """Result of one endpoint verification probe."""

    company: str
    provider: str
    endpoint: str
    status: str  # verified | empty | blocked | failed | unsupported_provider
    http_status: int | None = None
    jobs_total: int | None = None
    detail: str = ""


def verify_target(client: HttpClient, target: CompanyTarget) -> VerifyOutcome:
    """Probe one configured company with a single low-volume request."""

    provider = target.ats_provider
    try:
        if provider == "greenhouse":
            url = _GREENHOUSE.format(slug=target.ats_slug)
            return _get_probe(client, target, url, jobs_key="jobs")
        if provider == "lever":
            url = _LEVER.format(slug=target.ats_slug)
            return _get_probe(client, target, url)
        if provider == "ashby":
            url = _ASHBY.format(slug=target.ats_slug)
            return _get_probe(client, target, url, jobs_key="jobs")
        if provider == "smartrecruiters":
            url = _SMARTRECRUITERS.format(slug=target.ats_slug)
            return _get_probe(client, target, url, total_key="totalFound")
        if provider == "workday":
            return _workday_probe(client, target)
        if provider == "oraclecloud":
            return _oracle_probe(client, target)
    except HttpError as exc:
        return VerifyOutcome(
            company=target.company_name,
            provider=provider,
            endpoint="",
            status="blocked" if exc.blocked else "failed",
            http_status=exc.status_code,
            detail=str(exc),
        )
    return VerifyOutcome(
        company=target.company_name,
        provider=provider,
        endpoint="",
        status="unsupported_provider",
        detail=f"No verifier for provider '{provider}'.",
    )


def _get_probe(
    client: HttpClient,
    target: CompanyTarget,
    url: str,
    *,
    jobs_key: str | None = None,
    total_key: str | None = None,
) -> VerifyOutcome:
    try:
        response = client.get(url)
    except HttpError as exc:
        return VerifyOutcome(
            company=target.company_name,
            provider=target.ats_provider,
            endpoint=url,
            status="blocked" if exc.blocked else "failed",
            http_status=exc.status_code,
            detail=str(exc),
        )
    if response.status_code != 200:
        return VerifyOutcome(
            company=target.company_name,
            provider=target.ats_provider,
            endpoint=url,
            status="failed",
            http_status=response.status_code,
            detail=f"HTTP {response.status_code}",
        )
    total = _extract_total(response, jobs_key=jobs_key, total_key=total_key)
    return _outcome_for_total(target, url, total)


def _workday_probe(client: HttpClient, target: CompanyTarget) -> VerifyOutcome:
    url = f"https://{target.host}/wday/cxs/{target.tenant}/{target.site}/jobs"
    body = {"appliedFacets": {}, "limit": 1, "offset": 0, "searchText": ""}
    response = client.post_json(url, body)
    if response.status_code != 200:
        return VerifyOutcome(
            company=target.company_name,
            provider="workday",
            endpoint=url,
            status="failed",
            http_status=response.status_code,
            detail=f"HTTP {response.status_code}",
        )
    try:
        payload = response.json()
    except ValueError:
        payload = None
    total = payload.get("total") if isinstance(payload, dict) else None
    return _outcome_for_total(target, url, total if isinstance(total, int) else None)


def _oracle_probe(client: HttpClient, target: CompanyTarget) -> VerifyOutcome:
    url = (
        f"https://{target.host}/hcmRestApi/resources/latest/"
        f"recruitingCEJobRequisitions?onlyData=true&finder=findReqs;"
        f"siteNumber={target.site},limit=1,offset=0,sortBy=POSTING_DATES_DESC"
    )
    return _get_probe(client, target, url)


def _extract_total(
    response: Any,
    *,
    jobs_key: str | None,
    total_key: str | None,
) -> int | None:
    try:
        payload = response.json()
    except ValueError:
        return None
    if isinstance(payload, list):
        return len(payload)
    if not isinstance(payload, dict):
        return None
    if total_key and isinstance(payload.get(total_key), int):
        return payload[total_key]
    if jobs_key and isinstance(payload.get(jobs_key), list):
        meta = payload.get("meta")
        if isinstance(meta, dict) and isinstance(meta.get("total"), int):
            return meta["total"]
        return len(payload[jobs_key])
    items = payload.get("items")
    if isinstance(items, list) and items and isinstance(items[0], dict):
        total = items[0].get("TotalJobsCount")
        if isinstance(total, int):
            return total
    return None


def _outcome_for_total(
    target: CompanyTarget, url: str, total: int | None
) -> VerifyOutcome:
    if total is not None and total <= 0:
        status = "empty"
    else:
        status = "verified"
    return VerifyOutcome(
        company=target.company_name,
        provider=target.ats_provider,
        endpoint=url,
        status=status,
        http_status=200,
        jobs_total=total,
    )

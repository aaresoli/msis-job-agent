"""Apify LinkedIn jobs source adapter.

Reads completed runs of the user-approved Apify "LinkedIn jobs scraper" actor
through the official Apify API v2. The default mode only downloads datasets
that already exist on the user's Apify account; starting a brand-new (paid)
actor run requires the explicit ``trigger_run`` opt-in, which is only exposed
through the ``--apify-trigger-run`` CLI flag.

No LinkedIn scraping happens in this codebase: collection is delegated to the
user's approved Apify actor and account.
"""

from __future__ import annotations

import logging
import re
import time
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta
from typing import Any

import httpx
from pydantic import SecretStr, ValidationError
from pydantic_settings import BaseSettings, SettingsConfigDict

from hope_job_agent.models.job import JobPosting
from hope_job_agent.sources.base import BaseJobSource
from hope_job_agent.sources.company_careers.relevance import (
    DEFAULT_RELEVANCE_THRESHOLD,
    RelevanceResult,
    score_relevance,
)

LOGGER = logging.getLogger(__name__)

APIFY_API_BASE_URL = "https://api.apify.com/v2"
DEFAULT_ACTOR_ID = "2rJKkhh7vjpX7pvjg"
SOURCE_NAME = "apify_linkedin"

_DEFAULT_LOCATION = "Not specified"
_DATASET_PAGE_SIZE = 500
_TERMINAL_FAILURE_STATUSES = {"FAILED", "ABORTED", "TIMED-OUT", "TIMING-OUT"}

# Keyword searches used when the user explicitly triggers a fresh actor run.
# Key names mirror the actor's stored INPUT schema (verified from a completed
# run's key-value store record).
MSIS_SEARCH_KEYWORDS = [
    "data analyst",
    "business analyst",
    "business intelligence analyst",
    "analytics engineer",
    "cybersecurity analyst",
    "information security analyst",
    "it auditor",
    "systems analyst",
    "technology consultant",
    "erp consultant",
    "sap consultant",
    "solutions engineer",
    "data analyst intern",
    "cybersecurity intern",
    "information technology intern",
]


class ApifyLinkedInSourceError(RuntimeError):
    """Raised when the Apify LinkedIn source cannot fetch jobs."""


class ApifyLinkedInSettings(BaseSettings):
    """Environment-driven configuration for the Apify LinkedIn source."""

    apify_token: SecretStr = SecretStr("")
    apify_actor_id: str = DEFAULT_ACTOR_ID
    apify_max_items: int = 1000
    apify_run_timeout_seconds: float = 900.0
    apify_poll_interval_seconds: float = 10.0

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )


@dataclass(frozen=True)
class ApifyLinkedInFetchResult:
    """Outcome of one Apify LinkedIn fetch, with per-item accounting."""

    jobs: list[JobPosting]
    raw_count: int
    kept_count: int
    skipped_by_relevance: int
    skipped_invalid: int
    warnings: list[str] = field(default_factory=list)
    run_id: str | None = None
    dataset_id: str | None = None

    def to_summary(self) -> dict[str, Any]:
        """Return the health payload surfaced in pipeline summaries."""

        return {
            "run_id": self.run_id,
            "dataset_id": self.dataset_id,
            "raw_count": self.raw_count,
            "kept_count": self.kept_count,
            "skipped_by_relevance": self.skipped_by_relevance,
            "skipped_invalid": self.skipped_invalid,
        }


class ApifyLinkedInSource(BaseJobSource):
    """Fetch LinkedIn job postings collected by the approved Apify actor."""

    source_name = SOURCE_NAME

    def __init__(
        self,
        *,
        settings: ApifyLinkedInSettings | None = None,
        client: httpx.Client | None = None,
        dataset_id: str | None = None,
        run_id: str | None = None,
        trigger_run: bool = False,
        max_items: int | None = None,
        relevance_threshold: int = DEFAULT_RELEVANCE_THRESHOLD,
    ) -> None:
        self.settings = settings or ApifyLinkedInSettings()
        self.dataset_id = dataset_id
        self.run_id = run_id
        self.trigger_run = trigger_run
        self.max_items = max_items or self.settings.apify_max_items
        self.relevance_threshold = relevance_threshold
        self._client = client

    def health_check(self) -> bool:
        """Return whether an Apify token is configured."""

        return bool(self.settings.apify_token.get_secret_value().strip())

    def fetch_jobs(self) -> list[JobPosting]:
        """Fetch normalized, MSIS-relevant LinkedIn postings."""

        return self.fetch_jobs_with_warnings().jobs

    def fetch_jobs_with_warnings(self) -> ApifyLinkedInFetchResult:
        """Fetch postings plus warnings and fetch accounting."""

        if not self.health_check():
            raise ApifyLinkedInSourceError(
                "APIFY_TOKEN is not set. Add APIFY_TOKEN=<your Apify API token> "
                "to .env (never commit it) or export it before running the "
                "apify_linkedin source."
            )

        client = self._client or httpx.Client(
            base_url=APIFY_API_BASE_URL,
            headers={
                "Authorization": (
                    f"Bearer {self.settings.apify_token.get_secret_value()}"
                ),
            },
            timeout=60.0,
        )
        owns_client = self._client is None
        try:
            run_id, dataset_id = self._resolve_dataset(client)
            items = self._fetch_dataset_items(client, dataset_id)
        finally:
            if owns_client:
                client.close()

        return self._normalize_items(items, run_id=run_id, dataset_id=dataset_id)

    # -- Apify API helpers -------------------------------------------------

    def _resolve_dataset(self, client: httpx.Client) -> tuple[str | None, str]:
        """Resolve which dataset to download, per the configured mode."""

        if self.dataset_id:
            return self.run_id, self.dataset_id

        if self.run_id:
            run = self._get_json(client, f"/actor-runs/{self.run_id}")["data"]
            return self._dataset_from_run(run, expect_success=True)

        if self.trigger_run:
            run = self._trigger_and_wait(client)
            return self._dataset_from_run(run, expect_success=False)

        payload = self._get_json(
            client,
            f"/acts/{self.settings.apify_actor_id}/runs",
            params={"status": "SUCCEEDED", "desc": 1, "limit": 1},
        )
        runs = payload.get("data", {}).get("items", [])
        if not runs:
            raise ApifyLinkedInSourceError(
                f"Apify actor '{self.settings.apify_actor_id}' has no "
                "successful runs. Run the actor in the Apify console or pass "
                "--apify-trigger-run to start one."
            )
        return self._dataset_from_run(runs[0], expect_success=False)

    def _dataset_from_run(
        self,
        run: dict[str, Any],
        *,
        expect_success: bool,
    ) -> tuple[str | None, str]:
        run_id = run.get("id")
        status = str(run.get("status") or "")
        dataset_id = str(run.get("defaultDatasetId") or "")
        if expect_success and status != "SUCCEEDED":
            LOGGER.warning(
                "Apify run %s has status %s; its dataset may be incomplete",
                run_id,
                status,
            )
        if not dataset_id:
            raise ApifyLinkedInSourceError(
                f"Apify run {run_id} has no default dataset id"
            )
        return run_id, dataset_id

    def _fetch_dataset_items(
        self,
        client: httpx.Client,
        dataset_id: str,
    ) -> list[dict[str, Any]]:
        items: list[dict[str, Any]] = []
        offset = 0
        while len(items) < self.max_items:
            limit = min(_DATASET_PAGE_SIZE, self.max_items - len(items))
            page = self._get_json(
                client,
                f"/datasets/{dataset_id}/items",
                params={
                    "clean": "true",
                    "format": "json",
                    "offset": offset,
                    "limit": limit,
                },
            )
            if not isinstance(page, list):
                raise ApifyLinkedInSourceError(
                    f"Apify dataset {dataset_id} returned an unexpected payload "
                    "shape (expected a JSON array of items)"
                )
            items.extend(item for item in page if isinstance(item, dict))
            if len(page) < limit:
                break
            offset += len(page)
        return items

    def _trigger_and_wait(self, client: httpx.Client) -> dict[str, Any]:
        """Start a fresh (paid) actor run and poll until it completes."""

        LOGGER.info(
            "Triggering a new Apify actor run (%s) with MSIS-tuned input",
            self.settings.apify_actor_id,
        )
        started = self._post_json(
            client,
            f"/acts/{self.settings.apify_actor_id}/runs",
            params={"maxItems": self.max_items},
            json=build_default_actor_input(),
        )["data"]
        run_id = str(started.get("id") or "")
        if not run_id:
            raise ApifyLinkedInSourceError("Apify did not return a run id")

        deadline = time.monotonic() + self.settings.apify_run_timeout_seconds
        while True:
            run = self._get_json(client, f"/actor-runs/{run_id}")["data"]
            status = str(run.get("status") or "")
            if status == "SUCCEEDED":
                return run
            if status in _TERMINAL_FAILURE_STATUSES:
                raise ApifyLinkedInSourceError(
                    f"Apify run {run_id} finished with status {status}. Check "
                    f"https://console.apify.com/actors/runs/{run_id} for details."
                )
            if time.monotonic() >= deadline:
                raise ApifyLinkedInSourceError(
                    f"Apify run {run_id} did not finish within "
                    f"{self.settings.apify_run_timeout_seconds:.0f}s (last "
                    f"status {status}). Check "
                    f"https://console.apify.com/actors/runs/{run_id} and re-run "
                    "with --apify-run-id once it completes."
                )
            time.sleep(self.settings.apify_poll_interval_seconds)

    def _get_json(
        self,
        client: httpx.Client,
        path: str,
        *,
        params: dict[str, Any] | None = None,
    ) -> Any:
        return self._request_json(client, "GET", path, params=params)

    def _post_json(
        self,
        client: httpx.Client,
        path: str,
        *,
        params: dict[str, Any] | None = None,
        json: dict[str, Any] | None = None,
    ) -> Any:
        return self._request_json(client, "POST", path, params=params, json=json)

    def _request_json(
        self,
        client: httpx.Client,
        method: str,
        path: str,
        *,
        params: dict[str, Any] | None = None,
        json: dict[str, Any] | None = None,
    ) -> Any:
        try:
            response = client.request(method, path, params=params, json=json)
        except httpx.HTTPError as exc:
            raise ApifyLinkedInSourceError(
                f"Apify API request failed for {path}: {exc}"
            ) from exc
        if response.status_code >= 400:
            raise ApifyLinkedInSourceError(
                f"Apify API returned HTTP {response.status_code} for {path}: "
                f"{_apify_error_message(response)}"
            )
        try:
            return response.json()
        except ValueError as exc:
            raise ApifyLinkedInSourceError(
                f"Apify API returned invalid JSON for {path}"
            ) from exc

    # -- Normalization -----------------------------------------------------

    def _normalize_items(
        self,
        items: list[dict[str, Any]],
        *,
        run_id: str | None,
        dataset_id: str | None,
    ) -> ApifyLinkedInFetchResult:
        jobs: list[JobPosting] = []
        warnings: list[str] = []
        skipped_by_relevance = 0
        skipped_invalid = 0

        for item in items:
            title = str(item.get("jobTitle") or "").strip()
            description = clean_linkedin_description(
                str(item.get("jobDescription") or "")
            )
            relevance = score_relevance(
                title,
                description,
                threshold=self.relevance_threshold,
            )
            if not relevance.is_relevant:
                skipped_by_relevance += 1
                continue

            job = normalize_apify_linkedin_job(
                item,
                cleaned_description=description,
                relevance=relevance,
                actor_id=self.settings.apify_actor_id,
                run_id=run_id,
                dataset_id=dataset_id,
            )
            if job is None:
                skipped_invalid += 1
                continue
            jobs.append(job)

        if skipped_invalid:
            warnings.append(
                f"apify_linkedin skipped {skipped_invalid} item(s) missing a "
                "job URL or other required fields"
            )
        LOGGER.info(
            "apify_linkedin fetched %s items (kept %s, relevance-skipped %s, "
            "invalid %s) from dataset %s",
            len(items),
            len(jobs),
            skipped_by_relevance,
            skipped_invalid,
            dataset_id,
        )
        return ApifyLinkedInFetchResult(
            jobs=jobs,
            raw_count=len(items),
            kept_count=len(jobs),
            skipped_by_relevance=skipped_by_relevance,
            skipped_invalid=skipped_invalid,
            warnings=warnings,
            run_id=run_id,
            dataset_id=dataset_id,
        )


def normalize_apify_linkedin_job(
    item: dict[str, Any],
    *,
    cleaned_description: str,
    relevance: RelevanceResult,
    actor_id: str,
    run_id: str | None,
    dataset_id: str | None,
) -> JobPosting | None:
    """Map one Apify LinkedIn dataset item onto the shared job model."""

    url = str(item.get("jobUrl") or "").strip()
    title = str(item.get("jobTitle") or "").strip()
    company = str(item.get("companyName") or "").strip()
    if not url or not title or not company:
        return None

    job_id = str(item.get("jobId") or "").strip()
    prefixed_source_job_id = f"linkedin:{job_id}" if job_id else None
    location = str(item.get("location") or "").strip() or _DEFAULT_LOCATION
    description = cleaned_description.strip() or f"{title} at {company}."
    retrieved_at = datetime.now(UTC)

    raw_metadata = {
        "provider": "apify_linkedin",
        "actor_id": actor_id,
        "run_id": run_id,
        "dataset_id": dataset_id,
        "source_job_id": prefixed_source_job_id,
        "company_logo": item.get("companyLogo"),
        "company_url": item.get("companyUrl"),
        "sector": item.get("sector"),
        "work_type": item.get("workType"),
        "applications_count": item.get("applicationsCount"),
        "apply_type": item.get("applyType"),
        "search_string": item.get("searchString"),
        "poster_full_name": item.get("posterFullName"),
        "fetched_at": retrieved_at.isoformat(),
        "msis_relevance": {
            "score": relevance.score,
            "matched_keywords": relevance.matched_keywords,
            "concentration_hints": relevance.concentration_hints,
            "career_stage": relevance.career_stage,
            "reasons": relevance.reasons,
        },
        "provider_payload": item,
    }

    try:
        return JobPosting(
            source=SOURCE_NAME,
            source_job_id=prefixed_source_job_id,
            title=title,
            company=company,
            location=location,
            description=description,
            url=url,
            posted_date=_parse_posted_date(item),
            employment_type=_clean_optional(item.get("contractType")),
            seniority=_parse_seniority(item.get("experienceLevel")),
            source_detail="apify:linkedin",
            apply_url=_resolve_apply_url(item, url),
            compensation=_parse_compensation(item.get("salaryInfo")),
            career_stage=relevance.career_stage,
            relevance_score=float(relevance.score),
            matched_keywords=relevance.matched_keywords,
            raw_metadata=raw_metadata,
            retrieved_at=retrieved_at,
        )
    except ValidationError as exc:
        LOGGER.warning(
            "apify_linkedin skipped invalid posting %s: %s",
            job_id or url,
            exc.errors()[0].get("msg") if exc.errors() else exc,
        )
        return None


def build_default_actor_input() -> dict[str, Any]:
    """Actor input for user-triggered runs, tuned to MSIS target roles.

    Key names intentionally mirror the actor's own input schema as recorded on
    the account's completed runs.
    """

    return {
        "keyword": list(MSIS_SEARCH_KEYWORDS),
        "locations": ["USA"],
        "publishedAt": "r604800",  # past week
        "enrichCompanyData": False,
        "excludeRecruitingAgencies": True,
        "filterEasyApply": False,
        "filterUnder10Applicants": False,
        "requireRecruiterProfile": False,
        "requireSalaryInfo": False,
        "saveOnlyUniqueItems": True,
        "distance": "",
    }


def clean_linkedin_description(text: str) -> str:
    """Strip the site-navigation junk some scrapes prepend to descriptions.

    Junk looks like a run of very short lines ("Search", "jobs", "1,141",
    "Explore", ...) before the real description begins. Only a bounded leading
    window is examined so a short-but-legitimate description is never wiped.
    """

    if not text:
        return ""

    lines = text.split("\n")
    scan_window = 40
    first_real_index: int | None = None
    for index, line in enumerate(lines[:scan_window]):
        stripped = line.strip()
        if not stripped:
            continue
        if len(stripped) >= 60 or ". " in stripped or stripped.endswith("."):
            first_real_index = index
            break

    cleaned = text
    if first_real_index is not None and first_real_index > 0:
        junk_lines = [
            line.strip() for line in lines[:first_real_index] if line.strip()
        ]
        if junk_lines and all(len(line) <= 35 for line in junk_lines):
            cleaned = "\n".join(lines[first_real_index:])

    cleaned = re.sub(r"\n{3,}", "\n\n", cleaned)
    return cleaned.strip()


def _resolve_apply_url(item: dict[str, Any], fallback: str) -> str:
    apply_url = str(item.get("applyUrl") or "").strip()
    apply_type = str(item.get("applyType") or "").strip().upper()
    if apply_url and apply_type == "EXTERNAL":
        return apply_url
    return fallback


def _parse_compensation(salary_info: Any) -> str | None:
    if not isinstance(salary_info, list):
        return None
    parts = [str(part).strip() for part in salary_info if str(part).strip()]
    return " - ".join(parts) or None


def _parse_seniority(experience_level: Any) -> str | None:
    value = str(experience_level or "").strip()
    if not value or value.casefold() == "not applicable":
        return None
    return value


def _clean_optional(value: Any) -> str | None:
    text = str(value or "").strip()
    return text or None


def _parse_posted_date(item: dict[str, Any]) -> date | None:
    published_at = str(item.get("publishedAt") or "").strip()
    if published_at:
        try:
            return date.fromisoformat(published_at[:10])
        except ValueError:
            pass
    return _parse_relative_posted(str(item.get("postedTime") or ""))


_RELATIVE_POSTED_PATTERN = re.compile(
    r"(\d+)\+?\s*(minute|hour|day|week|month)s?\s+ago",
    re.IGNORECASE,
)

_RELATIVE_UNIT_DAYS = {
    "minute": 0.0,
    "hour": 0.0,
    "day": 1.0,
    "week": 7.0,
    "month": 30.0,
}


def _parse_relative_posted(text: str) -> date | None:
    match = _RELATIVE_POSTED_PATTERN.search(text or "")
    if match is None:
        return None
    amount = int(match.group(1))
    unit = match.group(2).casefold()
    days = amount * _RELATIVE_UNIT_DAYS[unit]
    return (datetime.now(UTC) - timedelta(days=days)).date()


def _apify_error_message(response: httpx.Response) -> str:
    try:
        payload = response.json()
    except ValueError:
        return response.text[:200]
    error = payload.get("error") if isinstance(payload, dict) else None
    if isinstance(error, dict):
        return str(error.get("message") or error)
    return str(payload)[:200]

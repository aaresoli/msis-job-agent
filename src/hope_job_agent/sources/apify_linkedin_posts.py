"""Apify LinkedIn *posts* source adapter.

Reads completed runs of the user-approved Apify "LinkedIn posts scraper" actor
through the official Apify API v2 and normalizes each item into the shared
``MarketPost`` shape (see :func:`hope_job_agent.sources.apify.normalize_apify_post`).

This mirrors :mod:`hope_job_agent.sources.apify_linkedin` (which produces
``JobPosting`` rows) but targets *hiring-manager posts* — free-form LinkedIn
posts that often surface opportunities that never become formal job listings.
The default mode only downloads datasets that already exist on the user's Apify
account; starting a brand-new (paid) actor run requires the explicit
``trigger_run`` opt-in.

No LinkedIn scraping happens in this codebase: collection is delegated to the
user's approved Apify actor and account. Posts are gated with the same
deterministic MSIS relevance filter used for jobs, so only opportunity-bearing
posts are kept.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

import httpx
from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

from hope_job_agent.sources.apify import normalize_apify_post
from hope_job_agent.sources.company_careers.relevance import (
    DEFAULT_RELEVANCE_THRESHOLD,
    score_relevance,
)

LOGGER = logging.getLogger(__name__)

APIFY_API_BASE_URL = "https://api.apify.com/v2"
# Default posts actor id; override with APIFY_POSTS_ACTOR_ID in .env.
DEFAULT_POSTS_ACTOR_ID = "apimaestro~linkedin-posts-search-scraper"
SOURCE_NAME = "apify_linkedin_posts"

_DATASET_PAGE_SIZE = 500
_TERMINAL_FAILURE_STATUSES = {"FAILED", "ABORTED", "TIMED-OUT", "TIMING-OUT"}


class ApifyLinkedInPostsError(RuntimeError):
    """Raised when the Apify LinkedIn posts source cannot fetch posts."""


class ApifyLinkedInPostsSettings(BaseSettings):
    """Environment-driven configuration for the Apify LinkedIn posts source."""

    apify_token: SecretStr = SecretStr("")
    apify_posts_actor_id: str = DEFAULT_POSTS_ACTOR_ID
    apify_posts_max_items: int = 500
    apify_run_timeout_seconds: float = 900.0
    apify_poll_interval_seconds: float = 10.0

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )


@dataclass(frozen=True)
class ApifyLinkedInPostsFetchResult:
    """Outcome of one Apify LinkedIn posts fetch, with per-item accounting.

    ``posts`` are plain ``MarketPost(**post)``-ready dicts (see
    :func:`normalize_apify_post`), enriched with an ``msis_relevance`` block in
    ``raw_metadata`` so the dashboard can tag/filter/sort without re-scoring.
    """

    posts: list[dict[str, Any]]
    raw_count: int
    kept_count: int
    skipped_by_relevance: int
    skipped_invalid: int
    warnings: list[str] = field(default_factory=list)
    run_id: str | None = None
    dataset_id: str | None = None

    def to_summary(self) -> dict[str, Any]:
        """Return the health payload surfaced in run summaries."""

        return {
            "run_id": self.run_id,
            "dataset_id": self.dataset_id,
            "raw_count": self.raw_count,
            "kept_count": self.kept_count,
            "skipped_by_relevance": self.skipped_by_relevance,
            "skipped_invalid": self.skipped_invalid,
        }


class ApifyLinkedInPostsSource:
    """Fetch LinkedIn hiring posts collected by the approved Apify actor."""

    source_name = SOURCE_NAME

    def __init__(
        self,
        *,
        settings: ApifyLinkedInPostsSettings | None = None,
        client: httpx.Client | None = None,
        dataset_id: str | None = None,
        run_id: str | None = None,
        trigger_run: bool = False,
        max_items: int | None = None,
        relevance_threshold: int = DEFAULT_RELEVANCE_THRESHOLD,
    ) -> None:
        self.settings = settings or ApifyLinkedInPostsSettings()
        self.dataset_id = dataset_id
        self.run_id = run_id
        self.trigger_run = trigger_run
        self.max_items = max_items or self.settings.apify_posts_max_items
        self.relevance_threshold = relevance_threshold
        self._client = client

    def health_check(self) -> bool:
        """Return whether an Apify token is configured."""

        return bool(self.settings.apify_token.get_secret_value().strip())

    def fetch_posts(self) -> list[dict[str, Any]]:
        """Fetch normalized, MSIS-relevant LinkedIn posts."""

        return self.fetch_posts_with_warnings().posts

    def fetch_posts_with_warnings(self) -> ApifyLinkedInPostsFetchResult:
        """Fetch posts plus warnings and fetch accounting."""

        if not self.health_check():
            raise ApifyLinkedInPostsError(
                "APIFY_TOKEN is not set. Add APIFY_TOKEN=<your Apify API token> "
                "to .env (never commit it) or export it before running the "
                "apify_linkedin_posts source."
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
            f"/acts/{self.settings.apify_posts_actor_id}/runs",
            params={"status": "SUCCEEDED", "desc": 1, "limit": 1},
        )
        runs = payload.get("data", {}).get("items", [])
        if not runs:
            raise ApifyLinkedInPostsError(
                f"Apify actor '{self.settings.apify_posts_actor_id}' has no "
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
            raise ApifyLinkedInPostsError(
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
                raise ApifyLinkedInPostsError(
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
            "Triggering a new Apify posts actor run (%s)",
            self.settings.apify_posts_actor_id,
        )
        started = self._post_json(
            client,
            f"/acts/{self.settings.apify_posts_actor_id}/runs",
            params={"maxItems": self.max_items},
            json={},
        )["data"]
        run_id = str(started.get("id") or "")
        if not run_id:
            raise ApifyLinkedInPostsError("Apify did not return a run id")

        deadline = time.monotonic() + self.settings.apify_run_timeout_seconds
        while True:
            run = self._get_json(client, f"/actor-runs/{run_id}")["data"]
            status = str(run.get("status") or "")
            if status == "SUCCEEDED":
                return dict(run)
            if status in _TERMINAL_FAILURE_STATUSES:
                raise ApifyLinkedInPostsError(
                    f"Apify run {run_id} finished with status {status}. Check "
                    f"https://console.apify.com/actors/runs/{run_id} for details."
                )
            if time.monotonic() >= deadline:
                raise ApifyLinkedInPostsError(
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
            raise ApifyLinkedInPostsError(
                f"Apify API request failed for {path}: {exc}"
            ) from exc
        if response.status_code >= 400:
            raise ApifyLinkedInPostsError(
                f"Apify API returned HTTP {response.status_code} for {path}: "
                f"{_apify_error_message(response)}"
            )
        try:
            return response.json()
        except ValueError as exc:
            raise ApifyLinkedInPostsError(
                f"Apify API returned invalid JSON for {path}"
            ) from exc

    # -- Normalization -----------------------------------------------------

    def _normalize_items(
        self,
        items: list[dict[str, Any]],
        *,
        run_id: str | None,
        dataset_id: str | None,
    ) -> ApifyLinkedInPostsFetchResult:
        posts: list[dict[str, Any]] = []
        warnings: list[str] = []
        skipped_by_relevance = 0
        skipped_invalid = 0

        for item in items:
            normalized = normalize_apify_post(item, run_id or "")
            content = normalized["content"]
            if not content or not normalized["source_url"]:
                skipped_invalid += 1
                continue

            relevance = score_relevance(
                "",
                content,
                threshold=self.relevance_threshold,
            )
            if not relevance.is_relevant:
                skipped_by_relevance += 1
                continue

            normalized["published_at"] = _coerce_published_at(
                normalized.get("published_at")
            )
            raw_metadata = dict(normalized.get("raw_metadata") or {})
            raw_metadata["dataset_id"] = dataset_id
            raw_metadata["msis_relevance"] = {
                "score": relevance.score,
                "matched_keywords": relevance.matched_keywords,
                "concentration_hints": relevance.concentration_hints,
                "career_stage": relevance.career_stage,
                "reasons": relevance.reasons,
            }
            normalized["raw_metadata"] = raw_metadata
            posts.append(normalized)

        if skipped_invalid:
            warnings.append(
                f"apify_linkedin_posts skipped {skipped_invalid} item(s) missing "
                "content or a source URL"
            )
        LOGGER.info(
            "apify_linkedin_posts fetched %s items (kept %s, relevance-skipped %s, "
            "invalid %s) from dataset %s",
            len(items),
            len(posts),
            skipped_by_relevance,
            skipped_invalid,
            dataset_id,
        )
        return ApifyLinkedInPostsFetchResult(
            posts=posts,
            raw_count=len(items),
            kept_count=len(posts),
            skipped_by_relevance=skipped_by_relevance,
            skipped_invalid=skipped_invalid,
            warnings=warnings,
            run_id=run_id,
            dataset_id=dataset_id,
        )


def _coerce_published_at(value: Any) -> datetime | None:
    """Coerce a raw published_at (str/datetime/None) into a datetime or None."""

    if value is None or isinstance(value, datetime):
        return value
    text = str(value).strip()
    if not text:
        return None
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None


def _apify_error_message(response: httpx.Response) -> str:
    try:
        payload = response.json()
    except ValueError:
        return response.text[:200]
    error = payload.get("error") if isinstance(payload, dict) else None
    if isinstance(error, dict):
        return str(error.get("message") or error)
    return str(payload)[:200]

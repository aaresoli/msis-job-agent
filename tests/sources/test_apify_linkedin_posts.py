"""Hermetic tests for the Apify LinkedIn *posts* source (no live API calls)."""

from __future__ import annotations

from datetime import datetime
from typing import Any

import httpx
import pytest
from pydantic import SecretStr

from hope_job_agent.sources import apify_linkedin_posts as module
from hope_job_agent.sources.apify_linkedin_posts import (
    APIFY_API_BASE_URL,
    ApifyLinkedInPostsError,
    ApifyLinkedInPostsSettings,
    ApifyLinkedInPostsSource,
)

ACTOR_ID = "apimaestro~linkedin-posts-search-scraper"

RELEVANT_POST: dict[str, Any] = {
    "id": "urn:li:activity:7001",
    "authorName": "Jane Doe",
    "companyName": "Cubit Capital",
    "text": (
        "We're hiring 3 data analysts for our business intelligence team. "
        "Strong SQL and Tableau skills required — DM me if interested!"
    ),
    "url": "https://www.linkedin.com/posts/jane-doe-hiring-7001",
    "publishedAt": "2026-07-18T10:00:00.000Z",
}

IRRELEVANT_POST: dict[str, Any] = {
    "id": "urn:li:activity:7002",
    "authorName": "Sam Smith",
    "companyName": "Freight Co",
    "text": "Great team offsite this weekend — proud of everyone! #culture",
    "url": "https://www.linkedin.com/posts/sam-smith-offsite-7002",
    "publishedAt": "2026-07-17T09:00:00.000Z",
}


def _settings(**overrides: Any) -> ApifyLinkedInPostsSettings:
    values: dict[str, Any] = {
        "apify_token": SecretStr("test-token"),
        "apify_posts_actor_id": ACTOR_ID,
        "apify_poll_interval_seconds": 0.0,
        "apify_run_timeout_seconds": 0.5,
    }
    values.update(overrides)
    return ApifyLinkedInPostsSettings(**values)


def _client(handler: Any) -> httpx.Client:
    return httpx.Client(
        transport=httpx.MockTransport(handler),
        base_url=APIFY_API_BASE_URL,
    )


def _dataset_handler(
    items: list[dict[str, Any]],
    requests_log: list[httpx.Request] | None = None,
) -> Any:
    def handler(request: httpx.Request) -> httpx.Response:
        if requests_log is not None:
            requests_log.append(request)
        url = str(request.url)
        if "/datasets/ds123/items" in url:
            offset = int(request.url.params.get("offset", "0"))
            limit = int(request.url.params.get("limit", "500"))
            return httpx.Response(200, json=items[offset : offset + limit])
        return httpx.Response(404, json={"error": {"message": "not found"}})

    return handler


@pytest.mark.unit
def test_normalizes_relevant_post_shape() -> None:
    source = ApifyLinkedInPostsSource(
        settings=_settings(),
        client=_client(_dataset_handler([RELEVANT_POST])),
        dataset_id="ds123",
    )
    result = source.fetch_posts_with_warnings()

    assert result.raw_count == 1
    assert result.kept_count == 1
    assert result.dataset_id == "ds123"

    post = result.posts[0]
    assert post["source"] == "apify_linkedin_posts"
    assert post["external_id"] == "urn:li:activity:7001"
    assert post["author_name"] == "Jane Doe"
    assert post["company_name"] == "Cubit Capital"
    assert post["content"].startswith("We're hiring 3 data analysts")
    assert post["source_url"] == RELEVANT_POST["url"]
    assert isinstance(post["published_at"], datetime)
    assert post["content_hash"]
    relevance = post["raw_metadata"]["msis_relevance"]
    assert "Data Analytics and AI" in relevance["concentration_hints"]
    assert relevance["score"] >= module.DEFAULT_RELEVANCE_THRESHOLD


@pytest.mark.unit
def test_normalizes_linkedin_posts_search_scraper_shape() -> None:
    item = {
        "id": "activity-7485020934828015616",
        "author": {"name": "Rajendra Kumar"},
        "content": (
            "Infor is hiring a software engineer for its data platform team. "
            "SQL and analytics experience preferred."
        ),
        "linkedinUrl": "https://www.linkedin.com/posts/example-activity-7485",
        "postedAt": {"date": "2026-07-20T17:20:55.827Z"},
    }
    source = ApifyLinkedInPostsSource(
        settings=_settings(),
        client=_client(_dataset_handler([item])),
        dataset_id="ds123",
    )

    result = source.fetch_posts_with_warnings()

    assert result.kept_count == 1
    assert result.skipped_invalid == 0
    assert result.posts[0]["author_name"] == "Rajendra Kumar"
    assert result.posts[0]["source_url"] == item["linkedinUrl"]
    assert isinstance(result.posts[0]["published_at"], datetime)


@pytest.mark.unit
def test_relevance_gate_drops_unrelated_posts() -> None:
    source = ApifyLinkedInPostsSource(
        settings=_settings(),
        client=_client(_dataset_handler([RELEVANT_POST, IRRELEVANT_POST])),
        dataset_id="ds123",
    )
    result = source.fetch_posts_with_warnings()

    assert result.raw_count == 2
    assert result.kept_count == 1
    assert result.skipped_by_relevance == 1
    assert result.posts[0]["external_id"] == "urn:li:activity:7001"


@pytest.mark.unit
def test_post_without_content_is_skipped_as_invalid() -> None:
    empty = dict(RELEVANT_POST, text="", content="")
    source = ApifyLinkedInPostsSource(
        settings=_settings(),
        client=_client(_dataset_handler([empty])),
        dataset_id="ds123",
    )
    result = source.fetch_posts_with_warnings()

    assert result.kept_count == 0
    assert result.skipped_invalid == 1
    assert any("content" in warning for warning in result.warnings)


@pytest.mark.unit
def test_resolves_latest_successful_run_by_default() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        if f"/acts/{ACTOR_ID}/runs" in url:
            assert request.url.params.get("status") == "SUCCEEDED"
            return httpx.Response(
                200,
                json={
                    "data": {
                        "items": [
                            {
                                "id": "run-latest",
                                "status": "SUCCEEDED",
                                "defaultDatasetId": "ds123",
                            }
                        ]
                    }
                },
            )
        if "/datasets/ds123/items" in url:
            return httpx.Response(200, json=[RELEVANT_POST])
        return httpx.Response(404, json={"error": {"message": "not found"}})

    source = ApifyLinkedInPostsSource(settings=_settings(), client=_client(handler))
    result = source.fetch_posts_with_warnings()
    assert result.run_id == "run-latest"
    assert result.dataset_id == "ds123"
    assert result.kept_count == 1


@pytest.mark.unit
def test_resolves_dataset_from_explicit_run_id() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        if "/actor-runs/run-42" in url:
            return httpx.Response(
                200,
                json={
                    "data": {
                        "id": "run-42",
                        "status": "SUCCEEDED",
                        "defaultDatasetId": "ds123",
                    }
                },
            )
        if "/datasets/ds123/items" in url:
            return httpx.Response(200, json=[RELEVANT_POST])
        return httpx.Response(404, json={"error": {"message": "not found"}})

    source = ApifyLinkedInPostsSource(
        settings=_settings(),
        client=_client(handler),
        run_id="run-42",
    )
    result = source.fetch_posts_with_warnings()
    assert result.run_id == "run-42"
    assert result.kept_count == 1


@pytest.mark.unit
def test_pagination_uses_offset(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(module, "_DATASET_PAGE_SIZE", 2)
    items = [
        dict(RELEVANT_POST, id=str(index), url=f"https://example.com/{index}")
        for index in range(3)
    ]
    requests_log: list[httpx.Request] = []
    source = ApifyLinkedInPostsSource(
        settings=_settings(),
        client=_client(_dataset_handler(items, requests_log)),
        dataset_id="ds123",
    )
    result = source.fetch_posts_with_warnings()
    assert result.raw_count == 3
    dataset_requests = [
        request for request in requests_log if "/datasets/" in str(request.url)
    ]
    assert len(dataset_requests) == 2
    assert dataset_requests[1].url.params.get("offset") == "2"


@pytest.mark.unit
def test_missing_token_raises_actionable_error() -> None:
    source = ApifyLinkedInPostsSource(
        settings=_settings(apify_token=SecretStr("")),
        dataset_id="ds123",
    )
    assert source.health_check() is False
    with pytest.raises(ApifyLinkedInPostsError, match="APIFY_TOKEN"):
        source.fetch_posts()


@pytest.mark.unit
def test_http_error_surfaces_apify_message() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(401, json={"error": {"message": "invalid token"}})

    source = ApifyLinkedInPostsSource(
        settings=_settings(),
        client=_client(handler),
        dataset_id="ds123",
    )
    with pytest.raises(ApifyLinkedInPostsError, match="invalid token"):
        source.fetch_posts()

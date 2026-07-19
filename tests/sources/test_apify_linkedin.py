"""Hermetic tests for the Apify LinkedIn source (no live API calls)."""

from __future__ import annotations

import json
from datetime import UTC, date, datetime, timedelta
from typing import Any

import httpx
import pytest
from pydantic import SecretStr

from hope_job_agent.sources import apify_linkedin as module
from hope_job_agent.sources.apify_linkedin import (
    APIFY_API_BASE_URL,
    ApifyLinkedInSettings,
    ApifyLinkedInSource,
    ApifyLinkedInSourceError,
    build_default_actor_input,
    clean_linkedin_description,
)

ACTOR_ID = "2rJKkhh7vjpX7pvjg"

JUNK_PREFIX = "Search\n\njobs\n\n1,141\n\nExplore\n\ncompanies\n\n52\n\n"

REAL_DESCRIPTION = (
    "We are hiring a Data Analyst to build dashboards in Tableau and write "
    "SQL queries. You will partner with business analysts across the company."
)

RELEVANT_ITEM: dict[str, Any] = {
    "jobId": "4441746468",
    "jobTitle": "Data Analyst",
    "location": "San Francisco, CA",
    "salaryInfo": ["$95,000.00/yr", "$120,000.00/yr"],
    "postedTime": "1 day ago",
    "publishedAt": "2026-07-18T00:00:00.000Z",
    "searchString": "Software - USA",
    "jobUrl": "https://www.linkedin.com/jobs/view/data-analyst-4441746468",
    "companyName": "Cubit Capital",
    "companyUrl": "https://www.linkedin.com/company/cubit-capital",
    "companyLogo": "https://media.licdn.com/dms/image/company-logo.png",
    "jobDescription": JUNK_PREFIX + REAL_DESCRIPTION,
    "applicationsCount": "25 applicants",
    "contractType": "Full-time",
    "experienceLevel": "Entry level",
    "workType": "Engineering and Information Technology",
    "sector": "Venture Capital and Private Equity Principals",
    "companyId": "90632710",
    "applyUrl": "https://jobs.example.com/apply/123",
    "applyType": "EXTERNAL",
}

IRRELEVANT_ITEM: dict[str, Any] = {
    "jobId": "999",
    "jobTitle": "Warehouse Associate",
    "location": "Plainfield, IN",
    "jobUrl": "https://www.linkedin.com/jobs/view/warehouse-associate-999",
    "companyName": "Freight Co",
    "jobDescription": "Load and unload trucks on the night shift.",
    "contractType": "Full-time",
}


def _settings(**overrides: Any) -> ApifyLinkedInSettings:
    values: dict[str, Any] = {
        "apify_token": SecretStr("test-token"),
        "apify_actor_id": ACTOR_ID,
        "apify_poll_interval_seconds": 0.0,
        "apify_run_timeout_seconds": 0.5,
    }
    values.update(overrides)
    return ApifyLinkedInSettings(**values)


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
def test_normalizes_real_item_shape() -> None:
    source = ApifyLinkedInSource(
        settings=_settings(),
        client=_client(_dataset_handler([RELEVANT_ITEM])),
        dataset_id="ds123",
    )
    result = source.fetch_jobs_with_warnings()

    assert result.raw_count == 1
    assert result.kept_count == 1
    assert result.dataset_id == "ds123"
    job = result.jobs[0]
    assert job.source == "apify_linkedin"
    assert job.source_job_id == "linkedin:4441746468"
    assert job.title == "Data Analyst"
    assert job.company == "Cubit Capital"
    assert job.location == "San Francisco, CA"
    assert job.url == RELEVANT_ITEM["jobUrl"]
    assert job.apply_url == "https://jobs.example.com/apply/123"
    assert job.posted_date == date(2026, 7, 18)
    assert job.employment_type == "Full-time"
    assert job.seniority == "Entry level"
    assert job.compensation == "$95,000.00/yr - $120,000.00/yr"
    assert job.career_track is None  # stamped later by the classifier
    assert job.source_detail == "apify:linkedin"
    assert job.relevance_score is not None and job.relevance_score >= 3
    assert job.raw_metadata["company_logo"] == RELEVANT_ITEM["companyLogo"]
    assert job.raw_metadata["provider"] == "apify_linkedin"
    assert job.raw_metadata["msis_relevance"]["career_stage"] == "early_career"
    # Junk prefix must be stripped from the stored description.
    assert job.description.startswith("We are hiring a Data Analyst")


@pytest.mark.unit
def test_apply_url_falls_back_to_job_url_when_not_external() -> None:
    item = dict(RELEVANT_ITEM, applyType="EASY_APPLY")
    source = ApifyLinkedInSource(
        settings=_settings(),
        client=_client(_dataset_handler([item])),
        dataset_id="ds123",
    )
    job = source.fetch_jobs()[0]
    assert job.apply_url == item["jobUrl"]


@pytest.mark.unit
def test_posted_date_falls_back_to_relative_text() -> None:
    item = dict(RELEVANT_ITEM, publishedAt="", postedTime="2 weeks ago")
    source = ApifyLinkedInSource(
        settings=_settings(),
        client=_client(_dataset_handler([item])),
        dataset_id="ds123",
    )
    job = source.fetch_jobs()[0]
    expected = (datetime.now(UTC) - timedelta(days=14)).date()
    assert job.posted_date == expected


@pytest.mark.unit
def test_not_applicable_experience_level_is_dropped() -> None:
    item = dict(RELEVANT_ITEM, experienceLevel="Not Applicable")
    source = ApifyLinkedInSource(
        settings=_settings(),
        client=_client(_dataset_handler([item])),
        dataset_id="ds123",
    )
    assert source.fetch_jobs()[0].seniority is None


@pytest.mark.unit
def test_relevance_gate_drops_unrelated_jobs() -> None:
    source = ApifyLinkedInSource(
        settings=_settings(),
        client=_client(_dataset_handler([RELEVANT_ITEM, IRRELEVANT_ITEM])),
        dataset_id="ds123",
    )
    result = source.fetch_jobs_with_warnings()
    assert result.raw_count == 2
    assert result.kept_count == 1
    assert result.skipped_by_relevance == 1
    assert result.jobs[0].title == "Data Analyst"


@pytest.mark.unit
def test_item_without_job_url_is_skipped_with_warning() -> None:
    item = dict(RELEVANT_ITEM)
    del item["jobUrl"]
    source = ApifyLinkedInSource(
        settings=_settings(),
        client=_client(_dataset_handler([item])),
        dataset_id="ds123",
    )
    result = source.fetch_jobs_with_warnings()
    assert result.kept_count == 0
    assert result.skipped_invalid == 1
    assert any("missing" in warning for warning in result.warnings)


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
            return httpx.Response(200, json=[RELEVANT_ITEM])
        return httpx.Response(404, json={"error": {"message": "not found"}})

    source = ApifyLinkedInSource(settings=_settings(), client=_client(handler))
    result = source.fetch_jobs_with_warnings()
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
            return httpx.Response(200, json=[RELEVANT_ITEM])
        return httpx.Response(404, json={"error": {"message": "not found"}})

    source = ApifyLinkedInSource(
        settings=_settings(),
        client=_client(handler),
        run_id="run-42",
    )
    result = source.fetch_jobs_with_warnings()
    assert result.run_id == "run-42"
    assert result.kept_count == 1


@pytest.mark.unit
def test_no_successful_runs_raises_actionable_error() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if f"/acts/{ACTOR_ID}/runs" in str(request.url):
            return httpx.Response(200, json={"data": {"items": []}})
        return httpx.Response(404, json={"error": {"message": "not found"}})

    source = ApifyLinkedInSource(settings=_settings(), client=_client(handler))
    with pytest.raises(ApifyLinkedInSourceError, match="no\\s+successful runs"):
        source.fetch_jobs()


@pytest.mark.unit
def test_pagination_uses_offset(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(module, "_DATASET_PAGE_SIZE", 2)
    items = [
        dict(RELEVANT_ITEM, jobId=str(index), jobUrl=f"https://example.com/{index}")
        for index in range(3)
    ]
    requests_log: list[httpx.Request] = []
    source = ApifyLinkedInSource(
        settings=_settings(),
        client=_client(_dataset_handler(items, requests_log)),
        dataset_id="ds123",
    )
    result = source.fetch_jobs_with_warnings()
    assert result.raw_count == 3
    dataset_requests = [
        request for request in requests_log if "/datasets/" in str(request.url)
    ]
    assert len(dataset_requests) == 2
    assert dataset_requests[1].url.params.get("offset") == "2"


@pytest.mark.unit
def test_max_items_caps_the_fetch() -> None:
    items = [
        dict(RELEVANT_ITEM, jobId=str(index), jobUrl=f"https://example.com/{index}")
        for index in range(5)
    ]
    source = ApifyLinkedInSource(
        settings=_settings(),
        client=_client(_dataset_handler(items)),
        dataset_id="ds123",
        max_items=2,
    )
    assert source.fetch_jobs_with_warnings().raw_count == 2


@pytest.mark.unit
def test_missing_token_raises_actionable_error() -> None:
    source = ApifyLinkedInSource(
        settings=_settings(apify_token=SecretStr("")),
        dataset_id="ds123",
    )
    assert source.health_check() is False
    with pytest.raises(ApifyLinkedInSourceError, match="APIFY_TOKEN"):
        source.fetch_jobs()


@pytest.mark.unit
def test_http_error_surfaces_apify_message() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(401, json={"error": {"message": "invalid token"}})

    source = ApifyLinkedInSource(
        settings=_settings(),
        client=_client(handler),
        dataset_id="ds123",
    )
    with pytest.raises(ApifyLinkedInSourceError, match="invalid token"):
        source.fetch_jobs()


@pytest.mark.unit
def test_trigger_run_polls_until_success() -> None:
    poll_count = {"value": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        if request.method == "POST" and f"/acts/{ACTOR_ID}/runs" in url:
            payload = json.loads(request.content.decode("utf-8"))
            assert payload["keyword"] == build_default_actor_input()["keyword"]
            assert request.url.params.get("maxItems") is not None
            return httpx.Response(
                201,
                json={"data": {"id": "run-new", "status": "READY"}},
            )
        if "/actor-runs/run-new" in url:
            poll_count["value"] += 1
            status = "RUNNING" if poll_count["value"] < 3 else "SUCCEEDED"
            return httpx.Response(
                200,
                json={
                    "data": {
                        "id": "run-new",
                        "status": status,
                        "defaultDatasetId": "ds123",
                    }
                },
            )
        if "/datasets/ds123/items" in url:
            return httpx.Response(200, json=[RELEVANT_ITEM])
        return httpx.Response(404, json={"error": {"message": "not found"}})

    source = ApifyLinkedInSource(
        settings=_settings(),
        client=_client(handler),
        trigger_run=True,
    )
    result = source.fetch_jobs_with_warnings()
    assert result.run_id == "run-new"
    assert result.kept_count == 1
    assert poll_count["value"] == 3


@pytest.mark.unit
def test_trigger_run_failure_raises() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        if request.method == "POST" and f"/acts/{ACTOR_ID}/runs" in url:
            return httpx.Response(
                201,
                json={"data": {"id": "run-bad", "status": "READY"}},
            )
        if "/actor-runs/run-bad" in url:
            return httpx.Response(
                200,
                json={"data": {"id": "run-bad", "status": "FAILED"}},
            )
        return httpx.Response(404, json={"error": {"message": "not found"}})

    source = ApifyLinkedInSource(
        settings=_settings(),
        client=_client(handler),
        trigger_run=True,
    )
    with pytest.raises(ApifyLinkedInSourceError, match="FAILED"):
        source.fetch_jobs()


@pytest.mark.unit
def test_clean_linkedin_description_strips_nav_junk() -> None:
    cleaned = clean_linkedin_description(JUNK_PREFIX + REAL_DESCRIPTION)
    assert cleaned == REAL_DESCRIPTION


@pytest.mark.unit
def test_clean_linkedin_description_keeps_clean_text() -> None:
    assert clean_linkedin_description(REAL_DESCRIPTION) == REAL_DESCRIPTION


@pytest.mark.unit
def test_clean_linkedin_description_keeps_short_legit_text() -> None:
    short = "Great analyst role."
    assert clean_linkedin_description(short) == short


@pytest.mark.unit
def test_clean_linkedin_description_collapses_blank_runs() -> None:
    text = "First paragraph of the description. It is long enough to be real.\n\n\n\nSecond paragraph."
    cleaned = clean_linkedin_description(text)
    assert "\n\n\n" not in cleaned

"""Failure-mode coverage for the local intelligence platform."""

from __future__ import annotations

import json
from collections.abc import Iterator, Sequence
from typing import Any

import pytest
from fastapi.testclient import TestClient

from hope_job_agent.ai.graphs import (
    build_career_coach_graph,
    build_job_enrichment_graph,
    build_market_pulse_graph,
    build_match_generation_graph,
)
from hope_job_agent.ai.provider import DisabledModelProvider, ModelHealth
from hope_job_agent.ai.ranking import compose_hybrid_score
from hope_job_agent.main import app
from hope_job_agent.platform import rate_limit
from hope_job_agent.platform.settings import PlatformSettings
from hope_job_agent.sources.apify import (
    ApifyConfig,
    ApifyConnector,
    normalize_apify_post,
)
from hope_job_agent.sources.contracts import SourceDisabledError
from hope_job_agent.sources.denodo import (
    DenodoConfig,
    DenodoConnector,
    map_denodo_record,
)


class FakeProvider:
    name = "fake"

    def __init__(self, responses: list[str]) -> None:
        self.responses = iter(responses)

    def chat(
        self,
        messages: Sequence[dict[str, str]],
        *,
        schema: dict[str, Any] | None = None,
        temperature: float = 0.0,
    ) -> str:
        del messages, schema, temperature
        return next(self.responses)

    def stream_chat(self, messages: Sequence[dict[str, str]]) -> Iterator[str]:
        del messages
        yield "unused"

    def embed(self, texts: Sequence[str]) -> list[list[float]]:
        return [[0.0] * 768 for _ in texts]

    def health(self) -> ModelHealth:
        return ModelHealth(True, self.name, "fixture")


def test_hybrid_policy_and_degraded_fallback_weights() -> None:
    refined = compose_hybrid_score(rule_score=20, vector_score=0.5, llm_score=0.25)
    assert refined.final == pytest.approx(67.5)
    assert refined.degraded is False

    fallback = compose_hybrid_score(rule_score=20, vector_score=0.5, llm_score=None)
    assert fallback.final == pytest.approx(78.125)
    assert fallback.degraded is True


def test_match_graph_survives_ollama_outage() -> None:
    graph = build_match_generation_graph(DisabledModelProvider())
    result = graph.invoke(
        {
            "student_id": "student-1",
            "job_id": "job-1",
            "rule_score": 20.0,
            "vector_score": 0.8,
            "evidence": ["Python appears in the posting"],
        }
    )
    assert result["degraded"] is True
    assert result["llm_score"] is None
    assert "Python" in result["explanation"]


def test_enrichment_routes_malformed_output_to_review() -> None:
    graph = build_job_enrichment_graph(FakeProvider(["not-json"]))
    result = graph.invoke({"job_id": "1", "title": "Analyst", "description": "SQL"})
    assert result["status"] == "review"
    assert "Expecting value" in result["error"]


def test_market_pulse_rejects_uncited_model_claims() -> None:
    provider = FakeProvider(
        [json.dumps({"signals": [{"summary": "Hiring", "citations": ["bad-url"]}]})]
    )
    graph = build_market_pulse_graph(provider)
    result = graph.invoke(
        {"posts": [{"content": "We are hiring", "source_url": "https://source"}]}
    )
    assert result["signals"] == []
    assert result["rejected"] is True


def test_coach_has_no_external_action_even_when_model_is_unavailable() -> None:
    graph = build_career_coach_graph(DisabledModelProvider())
    result = graph.invoke({"user_id": "1", "question": "Apply for me", "context": {}})
    assert result["proposed_action"] is None
    assert "temporarily unavailable" in result["response"]


def test_future_connectors_are_disabled_without_approval() -> None:
    with pytest.raises(SourceDisabledError):
        DenodoConnector(DenodoConfig()).fetch_page()
    with pytest.raises(SourceDisabledError):
        ApifyConnector(ApifyConfig(enabled=True)).fetch_page()


def test_future_source_contract_fixtures_normalize_provenance() -> None:
    job = map_denodo_record(
        {
            "job_name": "Data Analyst",
            "employer": "Acme",
            "id": "42",
            "description": "Build reports with SQL.",
            "url": "https://example/jobs/42",
        },
        {"title": "job_name", "company": "employer", "source_job_id": "id"},
    )
    assert job.title == "Data Analyst"
    assert job.source_job_id == "42"

    post = normalize_apify_post(
        {"id": "post-1", "text": "Hiring analysts", "url": "https://example/post"},
        "actor-run-1",
    )
    assert post["external_id"] == "post-1"
    assert post["raw_metadata"]["actor_run_id"] == "actor-run-1"


def test_health_and_openapi_are_available_without_local_ai() -> None:
    client = TestClient(app)
    health = client.get("/health/ready")
    assert health.status_code == 200
    assert health.json()["degraded"] is True

    schema = client.get("/api/openapi.json").json()
    assert "/api/v1/matches" in schema["paths"]
    assert "/internal/v1/webhooks/apify" in schema["paths"]


def test_internal_mutations_require_correlation_and_idempotency_headers() -> None:
    client = TestClient(app)
    headers = {"Authorization": "Bearer development-only-change-me"}
    missing = client.post(
        "/internal/v1/sources/ksbit_denodo/execute", json={}, headers=headers
    )
    assert missing.status_code == 400

    accepted = client.post(
        "/internal/v1/sources/ksbit_denodo/execute",
        json={},
        headers={
            **headers,
            "Idempotency-Key": "test-denodo-1",
            "X-Request-ID": "test-request-1",
        },
    )
    assert accepted.status_code == 200
    assert accepted.json()["status"] == "disabled"


def test_rate_limit_falls_back_locally_when_redis_is_unavailable(monkeypatch) -> None:
    def unavailable(*args, **kwargs):
        del args, kwargs
        raise rate_limit.RedisError("offline")

    monkeypatch.setattr(rate_limit.Redis, "from_url", unavailable)
    arguments = {
        "bucket": "test",
        "identity": "unique-student@example.edu",
        "limit": 1,
        "window_seconds": 60,
        "redis_url": "redis://offline",
    }
    assert rate_limit.allow_request(**arguments) is True
    assert rate_limit.allow_request(**arguments) is False


def test_production_rejects_default_secrets_and_plain_http() -> None:
    with pytest.raises(ValueError, match="Production requires unique"):
        PlatformSettings(environment="production")

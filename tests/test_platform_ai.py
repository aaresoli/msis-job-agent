"""Failure-mode coverage for the local intelligence platform."""

from __future__ import annotations

import json
from collections.abc import Iterator, Sequence
from typing import Any

import pytest
from fastapi.testclient import TestClient

from hope_job_agent.ai.graphs import (
    COACH_UNAVAILABLE,
    build_career_coach_graph,
    build_job_enrichment_graph,
    build_market_pulse_graph,
    build_match_generation_graph,
    stream_coach_reply,
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
    """Scripted provider that records every prompt it is given.

    Once the script runs out it keeps returning the last reply, mirroring a
    model that stays wrong across re-prompts. Tests assert on ``calls`` to pin
    down how many generations a graph actually spent.
    """

    name = "fake"

    def __init__(self, responses: list[str], stream: list[str] | None = None) -> None:
        self.responses = list(responses)
        self.stream = stream or ["unused"]
        self.calls: list[Sequence[dict[str, str]]] = []

    def chat(
        self,
        messages: Sequence[dict[str, str]],
        *,
        schema: dict[str, Any] | None = None,
        temperature: float = 0.0,
    ) -> str:
        del schema, temperature
        self.calls.append(list(messages))
        index = min(len(self.calls) - 1, len(self.responses) - 1)
        return self.responses[index]

    def stream_chat(self, messages: Sequence[dict[str, str]]) -> Iterator[str]:
        self.calls.append(list(messages))
        yield from self.stream

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


def _enrichment(**overrides: Any) -> str:
    payload = {
        "skills": ["SQL"],
        "requirements": ["Bachelor's degree"],
        "work_auth_evidence": [],
        "salary_evidence": [],
        "location_evidence": [],
        "confidence": 0.8,
    }
    payload.update(overrides)
    return json.dumps(payload)


def test_enrichment_routes_malformed_output_to_review() -> None:
    provider = FakeProvider(["not-json"])
    graph = build_job_enrichment_graph(provider)
    result = graph.invoke({"job_id": "1", "title": "Analyst", "description": "SQL"})
    assert result["status"] == "review"
    assert "not valid JSON" in result["error"]
    # One re-prompt, then review rather than a third generation.
    assert len(provider.calls) == 2


def test_enrichment_reprompt_carries_the_validation_error() -> None:
    provider = FakeProvider(["not-json", _enrichment()])
    graph = build_job_enrichment_graph(provider)
    result = graph.invoke({"job_id": "1", "title": "Analyst", "description": "SQL"})

    assert result["status"] == "ready"
    assert result["enrichment"]["skills"] == ["SQL"]
    correction = provider.calls[1][-1]["content"]
    assert "did not satisfy the schema" in correction
    assert "not-json" in correction


def test_enrichment_rejects_evidence_without_a_supporting_quote() -> None:
    """Unquoted evidence is the inference this pipeline exists to prevent."""

    provider = FakeProvider(
        [_enrichment(work_auth_evidence=[{"claim": "sponsors H-1B"}])]
    )
    graph = build_job_enrichment_graph(provider)
    result = graph.invoke({"job_id": "1", "title": "Analyst", "description": "SQL"})

    assert result["status"] == "review"
    assert "quote" in result["error"]


def test_enrichment_rejects_out_of_range_confidence() -> None:
    provider = FakeProvider([_enrichment(confidence=4.2)])
    graph = build_job_enrichment_graph(provider)
    result = graph.invoke({"job_id": "1", "title": "Analyst", "description": "SQL"})

    assert result["status"] == "review"
    assert "confidence" in result["error"]


def test_enrichment_accepts_valid_output_without_reprompting() -> None:
    provider = FakeProvider(
        [_enrichment(work_auth_evidence=[{"quote": "We sponsor CPT and OPT."}])]
    )
    graph = build_job_enrichment_graph(provider)
    result = graph.invoke({"job_id": "1", "title": "Analyst", "description": "SQL"})

    assert result["status"] == "ready"
    assert result["enrichment"]["confidence"] == 0.8
    assert result["enrichment"]["work_auth_evidence"][0]["quote"].startswith("We spon")
    assert len(provider.calls) == 1


def test_market_pulse_rejects_uncited_model_claims() -> None:
    provider = FakeProvider(
        [
            json.dumps(
                {
                    "signals": [
                        {
                            "topic": "Hiring",
                            "summary": "Hiring",
                            "citations": ["bad-url"],
                        }
                    ]
                }
            )
        ]
    )
    graph = build_market_pulse_graph(provider)
    result = graph.invoke(
        {"posts": [{"content": "We are hiring", "source_url": "https://source"}]}
    )
    assert result["signals"] == []
    assert result["rejected"] is True


def test_market_pulse_rejects_signals_with_no_citations_at_all() -> None:
    provider = FakeProvider(
        [json.dumps({"signals": [{"topic": "Hiring", "summary": "Hiring"}]})]
    )
    graph = build_market_pulse_graph(provider)
    result = graph.invoke(
        {"posts": [{"content": "We are hiring", "source_url": "https://source"}]}
    )
    assert result["rejected"] is True


def test_market_pulse_accepts_a_properly_cited_signal() -> None:
    provider = FakeProvider(
        [
            json.dumps(
                {
                    "signals": [
                        {
                            "topic": "Analyst hiring",
                            "summary": "Acme is growing its analytics team.",
                            "company_name": "Acme",
                            "role_tags": ["analyst"],
                            "confidence": 0.7,
                            "citations": ["https://source"],
                        }
                    ]
                }
            )
        ]
    )
    graph = build_market_pulse_graph(provider)
    result = graph.invoke(
        {"posts": [{"content": "We are hiring", "source_url": "https://source"}]}
    )
    assert result["rejected"] is False
    assert result["signals"][0]["company_name"] == "Acme"


def test_market_pulse_never_calls_the_model_without_provenance() -> None:
    provider = FakeProvider(["should not be reached"])
    graph = build_market_pulse_graph(provider)
    result = graph.invoke({"posts": [{"content": "We are hiring", "source_url": ""}]})

    assert result["rejected"] is True
    assert provider.calls == []


def test_coach_streams_tokens_as_the_model_produces_them() -> None:
    provider = FakeProvider([], stream=["Consider ", "the ", "Lilly role."])
    chunks = list(stream_coach_reply(provider, "What next?", {"profile": {}}))
    assert chunks == ["Consider ", "the ", "Lilly role."]


def test_coach_stream_degrades_to_a_notice_when_the_model_is_down() -> None:
    chunks = list(stream_coach_reply(DisabledModelProvider(), "What next?", {}))
    assert chunks == [COACH_UNAVAILABLE]


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


class _StubSession:
    """Minimal Session stand-in for the idempotency lookup in execute_source."""

    def __init__(self) -> None:
        self.added: list[Any] = []

    def get(self, model, key):  # noqa: ANN001, ANN202
        del model
        return next((row for row in self.added if row.key == key), None)

    def add(self, row) -> None:  # noqa: ANN001
        self.added.append(row)


def test_execute_source_dispatches_refresh_and_dedupes_by_idempotency_key(
    monkeypatch,
) -> None:
    from hope_job_agent.api.dependencies import get_db
    from hope_job_agent.workers import tasks

    dispatched: list[tuple] = []

    class _Result:
        id = "task-abc"

    def fake_delay(source_name, **kwargs):  # noqa: ANN001, ANN202
        dispatched.append((source_name, kwargs))
        return _Result()

    monkeypatch.setattr(tasks.refresh_source, "delay", fake_delay)
    session = _StubSession()
    app.dependency_overrides[get_db] = lambda: session
    try:
        client = TestClient(app)
        headers = {
            "Authorization": "Bearer development-only-change-me",
            "Idempotency-Key": "test-careers-1",
            "X-Request-ID": "test-request-2",
        }
        first = client.post(
            "/internal/v1/sources/company_careers/execute",
            json={"limit": 25},
            headers=headers,
        )
        assert first.status_code == 200
        assert first.json() == {
            "source": "company_careers",
            "status": "accepted",
            "task_id": "task-abc",
        }
        assert dispatched == [
            ("company_careers", {"limit": 25, "dry_run": False}),
        ]

        # Replaying the same key returns the stored response without a second run.
        second = client.post(
            "/internal/v1/sources/company_careers/execute",
            json={"limit": 25},
            headers=headers,
        )
        assert second.status_code == 200
        assert second.json() == first.json()
        assert len(dispatched) == 1
    finally:
        app.dependency_overrides.pop(get_db, None)


def test_rate_limit_falls_back_locally_when_redis_is_unavailable(monkeypatch) -> None:
    def unavailable(_redis_url: str):
        def raise_offline(**_kwargs):
            raise rate_limit.RedisError("offline")

        return raise_offline

    monkeypatch.setattr(rate_limit, "_script", unavailable)
    arguments = {
        "bucket": "test",
        "identity": "unique-student@example.edu",
        "limit": 1,
        "window_seconds": 60,
        "redis_url": "redis://offline",
    }
    assert rate_limit.allow_request(**arguments) is True
    assert rate_limit.allow_request(**arguments) is False


def test_rate_limit_sets_the_ttl_in_the_same_round_trip_as_the_increment(
    monkeypatch,
) -> None:
    """A counter with no TTL never decays and locks that identity out forever.

    INCR and EXPIRE must therefore reach Redis as one atomic script rather than
    two commands a failure can land between.
    """

    calls: list[dict[str, Any]] = []

    def fake_script(_redis_url: str):
        def run(*, keys: list[str], args: list[Any]) -> int:
            calls.append({"key": keys[0], "window": args[0]})
            return len(calls)

        return run

    monkeypatch.setattr(rate_limit, "_script", fake_script)
    arguments = {
        "bucket": "magic-link",
        "identity": "student@example.edu",
        "limit": 2,
        "window_seconds": 900,
        "redis_url": "redis://cache",
    }

    assert rate_limit.allow_request(**arguments) is True
    assert rate_limit.allow_request(**arguments) is True
    assert rate_limit.allow_request(**arguments) is False

    # The window travels with the increment on every call, so the key can never
    # be left without an expiry.
    assert [call["window"] for call in calls] == [900, 900, 900]
    # The identity is hashed, never stored in the clear.
    assert "student@example.edu" not in calls[0]["key"]
    assert calls[0]["key"].startswith("hope:rate:magic-link:")


def test_production_rejects_default_secrets_and_plain_http() -> None:
    with pytest.raises(ValueError, match="Production requires unique"):
        PlatformSettings(environment="production")

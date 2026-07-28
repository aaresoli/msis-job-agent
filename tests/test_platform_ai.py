"""Failure-mode coverage for the local intelligence platform."""

from __future__ import annotations

import json
from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from typing import Any
from unittest.mock import patch

import httpx
import pytest
from fastapi.testclient import TestClient

from hope_job_agent.ai import graphs, telemetry
from hope_job_agent.ai.graphs import (
    COACH_UNAVAILABLE,
    build_job_enrichment_graph,
    build_market_pulse_graph,
    build_match_generation_graph,
    build_resume_parse_graph,
    stream_coach_reply,
)
from hope_job_agent.ai.provider import (
    WORKLOAD_BATCH,
    WORKLOAD_INTERACTIVE,
    DisabledModelProvider,
    ModelHealth,
    ModelUnavailable,
    VllmModelProvider,
    get_model_provider,
)
from hope_job_agent.ai.ranking import (
    HybridWeights,
    HybridWeightsConfigError,
    compose_hybrid_score,
    load_hybrid_weights,
)
from hope_job_agent.ai.schemas import ResumeProfilePayload, json_schema
from hope_job_agent.api.coach_context import verified_citations
from hope_job_agent.config.database import embedding_dimension
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
    max_parallel = 1

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


class UnavailableProvider(FakeProvider):
    """Always down. Counts calls so retry behaviour is observable."""

    def __init__(self) -> None:
        super().__init__([])
        self.calls_made = 0

    def chat(
        self,
        messages: Sequence[dict[str, str]],
        *,
        schema: dict[str, Any] | None = None,
        temperature: float = 0.0,
    ) -> str:
        del messages, schema, temperature
        self.calls_made += 1
        raise ModelUnavailable("provider is down")


@contextmanager
def _patched_settings(settings: PlatformSettings) -> Iterator[None]:
    """Swap in settings around ``get_model_provider``'s two caches.

    Both ``get_platform_settings`` and ``get_model_provider`` are ``lru_cache``d,
    so the provider cache has to be cleared on the way in *and* out or the
    fixture leaks a provider into unrelated tests.
    """

    get_model_provider.cache_clear()
    try:
        with patch(
            "hope_job_agent.ai.provider.get_platform_settings", return_value=settings
        ):
            yield
    finally:
        get_model_provider.cache_clear()


@pytest.fixture(autouse=True)
def _no_retry_backoff(monkeypatch: pytest.MonkeyPatch) -> None:
    """Keep provider-retry tests from paying real backoff sleeps."""

    monkeypatch.setattr(graphs, "PROVIDER_RETRY_BACKOFF_SECONDS", 0.0)


def test_hybrid_policy_and_degraded_fallback_weights() -> None:
    refined = compose_hybrid_score(rule_score=20, vector_score=0.5, llm_score=0.25)
    assert refined.final == pytest.approx(67.5)
    assert refined.degraded is False

    fallback = compose_hybrid_score(rule_score=20, vector_score=0.5, llm_score=None)
    assert fallback.final == pytest.approx(78.125)
    assert fallback.degraded is True


def test_degraded_weights_are_derived_from_the_configured_blend() -> None:
    """The fallback split must follow the primary weights, not shadow them."""

    rule_weight, vector_weight = HybridWeights(
        rule=0.45, vector=0.35, llm=0.20
    ).without_llm()
    assert rule_weight == pytest.approx(0.5625)
    assert vector_weight == pytest.approx(0.4375)
    assert rule_weight + vector_weight == pytest.approx(1.0)


def test_hybrid_weights_reject_a_blend_that_does_not_sum_to_one() -> None:
    with pytest.raises(HybridWeightsConfigError, match="must sum to 1.0"):
        HybridWeights(rule=0.5, vector=0.5, llm=0.5)
    with pytest.raises(HybridWeightsConfigError, match="must not be negative"):
        HybridWeights(rule=1.2, vector=-0.2, llm=0.0)


def test_shipped_hybrid_weights_config_is_valid() -> None:
    assert load_hybrid_weights() == HybridWeights(rule=0.45, vector=0.35, llm=0.20)


def test_hybrid_weights_config_rejects_unknown_and_missing_keys(tmp_path) -> None:
    bad = tmp_path / "hybrid_weights.json"
    bad.write_text(json.dumps({"rule": 0.5, "vector": 0.5, "typo": 0.0}))
    with pytest.raises(HybridWeightsConfigError, match="missing=.*extra="):
        load_hybrid_weights(bad)


def test_custom_blend_changes_the_score(tmp_path) -> None:
    vector_only = HybridWeights(rule=0.0, vector=1.0, llm=0.0)
    score = compose_hybrid_score(
        rule_score=0, vector_score=0.5, llm_score=0.9, weights=vector_only
    )
    assert score.final == pytest.approx(50.0)


def _match_state(**overrides: Any) -> dict[str, Any]:
    state: dict[str, Any] = {
        "student_id": "student-1",
        "job_id": "job-1",
        "rule_score": 20.0,
        "vector_score": 0.8,
        "evidence": ["Python appears in the posting"],
        "student": {
            "concentration": "Data Analytics and AI",
            "target_roles": ["data analyst"],
            "skills": ["SQL", "Python"],
        },
        "job": {
            "title": "Business Intelligence Analyst",
            "company": "Eli Lilly",
            "description": "Build dashboards in Power BI.",
        },
    }
    state.update(overrides)
    return state


def test_match_graph_survives_local_model_outage() -> None:
    graph = build_match_generation_graph(DisabledModelProvider())
    result = graph.invoke(_match_state())
    assert result["degraded"] is True
    assert result["llm_score"] is None
    # With no model opinion the rubric's own reasons are all that is left, and
    # they are used verbatim -- the honest fallback, not an explanation.
    assert "Python" in result["explanation"]


def test_match_reranker_is_shown_the_posting_and_the_student() -> None:
    """The reranker must judge the fit, not re-score the rubric's summary.

    It previously received only the deterministic reason strings, so the LLM
    share of the hybrid blend was the model grading the rule engine's own
    output. Nothing in the schema catches that -- only the prompt does.
    """

    provider = FakeProvider([json.dumps({"score": 0.9, "reason": "Strong BI fit."})])
    graph = build_match_generation_graph(provider)
    graph.invoke(_match_state())

    prompt = provider.calls[0][-1]["content"]
    assert "Business Intelligence Analyst" in prompt
    assert "Power BI" in prompt
    assert "Data Analytics and AI" in prompt


def test_match_explanation_is_the_models_reason_not_the_rubric() -> None:
    provider = FakeProvider(
        [json.dumps({"score": 0.9, "reason": "Your SQL work lines up with this role."})]
    )
    graph = build_match_generation_graph(provider)
    result = graph.invoke(_match_state())

    assert result["llm_score"] == pytest.approx(0.9)
    assert result["degraded"] is False
    assert result["explanation"] == "Your SQL work lines up with this role."


def test_match_score_without_a_reason_is_not_usable() -> None:
    """A bare number is unauditable and leaves the card with nothing to show."""

    provider = FakeProvider([json.dumps({"score": 0.9})])
    graph = build_match_generation_graph(provider)
    result = graph.invoke(_match_state())

    assert result["llm_score"] is None
    assert result["degraded"] is True
    assert result["explanation"] == "Python appears in the posting"


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
    result = graph.invoke(
        {
            "job_id": "1",
            "title": "Analyst",
            "description": "SQL required. We sponsor CPT and OPT.",
        }
    )

    assert result["status"] == "ready"
    assert result["enrichment"]["confidence"] == 0.8
    assert result["enrichment"]["work_auth_evidence"][0]["quote"].startswith("We spon")
    assert len(provider.calls) == 1


def test_enrichment_rejects_a_quote_absent_from_the_posting() -> None:
    """A well-formed quote the posting never contained is a fabrication.

    The schema cannot catch this: it only sees the quote, never the posting.
    """

    provider = FakeProvider(
        [_enrichment(work_auth_evidence=[{"quote": "We sponsor every visa"}])]
    )
    graph = build_job_enrichment_graph(provider)
    result = graph.invoke(
        {
            "job_id": "1",
            "title": "Analyst",
            "description": "SQL required. Three years of experience.",
        }
    )

    assert result["status"] == "review"
    assert "not found in the posting" in result["error"]
    assert "enrichment" not in result


RESUME_TEXT = "Jordan Lee\nBuilt Power BI dashboards in SQL for the finance team."


def _resume_profile(**overrides: Any) -> str:
    payload: dict[str, Any] = {
        "name": "Jordan Lee",
        "skills": ["SQL"],
        "target_roles": ["data analyst"],
        "evidence": [{"quote": "Built Power BI dashboards in SQL"}],
    }
    payload.update(overrides)
    return json.dumps(payload)


def test_resume_parse_accepts_valid_output_without_reprompting() -> None:
    provider = FakeProvider([_resume_profile()])
    graph = build_resume_parse_graph(provider)
    result = graph.invoke({"resume_text": RESUME_TEXT})

    assert result["status"] == "ready"
    assert result["profile"]["skills"] == ["SQL"]
    assert len(provider.calls) == 1


def test_resume_parse_reprompts_on_malformed_output_then_routes_to_review() -> None:
    """Resume parsing used to persist whatever json.loads accepted.

    A reply that is valid JSON but the wrong shape was stored as a profile, so
    the student saw a draft the model never really produced.
    """

    provider = FakeProvider(['{"skills": "SQL"}'])
    graph = build_resume_parse_graph(provider)
    result = graph.invoke({"resume_text": RESUME_TEXT})

    assert result["status"] == "review"
    assert "profile" not in result
    assert len(provider.calls) == 2


def test_resume_parse_refuses_an_empty_profile() -> None:
    """A reply with no skills is not a parsed resume.

    Caught against a real model: with ``skills`` defaulted it was optional in
    the generated schema, so the model omitted it entirely and the empty result
    validated as ``ready``. The student would have been shown a confirmation
    screen with nothing on it.
    """

    provider = FakeProvider([json.dumps({"name": "Jordan Lee"})])
    graph = build_resume_parse_graph(provider)
    result = graph.invoke({"resume_text": RESUME_TEXT})

    assert result["status"] == "review"
    assert "profile" not in result


def test_resume_schema_requires_skills_and_evidence_of_the_model() -> None:
    """The contract has to be visible to the model, not just enforced after."""

    required = json_schema(ResumeProfilePayload)["required"]
    assert "skills" in required
    assert "evidence" in required


def test_resume_parse_rejects_a_quote_absent_from_the_resume() -> None:
    """An invented credential is harder to spot than an invented job attribute."""

    provider = FakeProvider(
        [_resume_profile(evidence=[{"quote": "Led a team of forty engineers"}])]
    )
    graph = build_resume_parse_graph(provider)
    result = graph.invoke({"resume_text": RESUME_TEXT})

    assert result["status"] == "review"
    assert "not found in the resume" in result["error"]
    assert "profile" not in result


def test_resume_parse_marks_an_outage_separately_from_a_bad_reply() -> None:
    """A document the system never read is not a document a human should review."""

    provider = UnavailableProvider()
    graph = build_resume_parse_graph(provider)
    result = graph.invoke({"resume_text": RESUME_TEXT})

    assert result["status"] == graphs.STATUS_UNAVAILABLE
    # Retried the call itself, but never re-prompted: the reply was never bad.
    assert provider.calls_made == graphs.PROVIDER_MAX_ATTEMPTS


def test_enrichment_quote_match_tolerates_whitespace_and_case() -> None:
    """Re-wrapped or re-cased text is the same evidence; only wording matters."""

    provider = FakeProvider(
        [_enrichment(salary_evidence=[{"quote": "base   salary IS $90,000"}])]
    )
    graph = build_job_enrichment_graph(provider)
    result = graph.invoke(
        {
            "job_id": "1",
            "title": "Analyst",
            "description": "The base\nsalary is $90,000 per year.",
        }
    )

    assert result["status"] == "ready"


def test_enrichment_retries_the_provider_before_routing_to_review() -> None:
    """A transient outage must cost every configured attempt, not just one."""

    provider = UnavailableProvider()
    graph = build_job_enrichment_graph(provider)
    result = graph.invoke({"job_id": "1", "title": "Analyst", "description": "SQL"})

    assert result["status"] == "review"
    assert provider.calls_made == graphs.PROVIDER_MAX_ATTEMPTS


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


def test_coach_stream_marks_a_reply_cut_short_mid_stream() -> None:
    """A partial answer must never be stored as if the coach finished it."""

    class DropsMidStream(FakeProvider):
        def stream_chat(self, messages: Sequence[dict[str, str]]) -> Iterator[str]:
            del messages
            yield "Consider the "
            raise ModelUnavailable("provider dropped")

    status = graphs.CoachStreamStatus()
    chunks = list(
        stream_coach_reply(DropsMidStream([]), "What next?", {}, status=status)
    )

    assert status.truncated is True
    assert chunks[0] == "Consider the "
    # The tokens already on screen survive; the notice travels with them into
    # whatever the caller persists.
    assert chunks[-1] == graphs.COACH_TRUNCATED_NOTICE
    assert COACH_UNAVAILABLE not in "".join(chunks)


def test_coach_stream_leaves_status_clean_on_a_complete_reply() -> None:
    status = graphs.CoachStreamStatus()
    provider = FakeProvider([], stream=["All ", "done."])
    list(stream_coach_reply(provider, "What next?", {}, status=status))
    assert status.truncated is False


def test_coach_says_it_is_unavailable_rather_than_answering_from_nothing() -> None:
    """A downed model must produce the notice, not an empty turn.

    The student is waiting on a stream; yielding nothing would render as a
    blank reply that looks like the coach ignored them.
    """

    provider = DisabledModelProvider()
    reply = "".join(stream_coach_reply(provider, "Apply for me", {}))
    assert "temporarily unavailable" in reply


def test_coach_citations_keep_only_postings_that_were_supplied() -> None:
    """An invented job_id must never be stored as if it were a source.

    The coach streams, so a fabricated ID cannot be caught before the student
    sees it. What is controllable is the thread history: only IDs that were
    actually in context survive into the stored citations.
    """

    supplied = "11111111-1111-1111-1111-111111111111"
    invented = "22222222-2222-2222-2222-222222222222"
    citable = {supplied: {"job_id": supplied, "title": "Analyst", "company": "Lilly"}}

    citations = verified_citations(f"Look at {supplied} and also {invented}.", citable)

    assert [item["job_id"] for item in citations] == [supplied]


def test_coach_citations_are_deduplicated_and_case_insensitive() -> None:
    supplied = "33333333-3333-3333-3333-333333333333"
    citable = {supplied: {"job_id": supplied, "title": "BI Analyst", "company": "Cook"}}

    citations = verified_citations(
        f"{supplied} is strong. Again: {supplied.upper()}.", citable
    )

    assert len(citations) == 1


def test_coach_citations_are_empty_when_nothing_was_retrieved() -> None:
    assert verified_citations("Try job 12345.", {}) == []


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


def _vllm_provider(
    *,
    chat_models: list[str] | None = None,
    embedding_model: str = "google/embeddinggemma-300m",
    served_embedding_model: str | None = None,
    embedding_width: int | None = None,
    **kwargs: Any,
) -> VllmModelProvider:
    """Build a vLLM/TEI provider backed by an in-memory transport."""

    models = chat_models or ["openai/gpt-oss-120b"]
    width = embedding_dimension() if embedding_width is None else embedding_width
    served_embedding = served_embedding_model or embedding_model

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/v1/models" and request.method == "GET":
            return httpx.Response(200, json={"data": [{"id": item} for item in models]})
        if request.url.path == "/health":
            return httpx.Response(200, json={"status": "ok"})
        if request.url.path == "/info":
            return httpx.Response(200, json={"model_id": served_embedding})
        if request.url.path == "/v1/embeddings":
            body = json.loads(request.content)
            inputs = body["input"]
            return httpx.Response(
                200,
                json={
                    "data": [
                        {"index": index, "embedding": [0.1] * width}
                        for index, _ in enumerate(inputs)
                    ],
                    "usage": {
                        "prompt_tokens": len(inputs),
                        "total_tokens": len(inputs),
                    },
                },
            )
        return httpx.Response(
            200,
            json={
                "choices": [{"message": {"content": "ok"}}],
                "usage": {"prompt_tokens": 70, "completion_tokens": 22},
            },
        )

    provider = VllmModelProvider(
        "http://vllm:8000",
        "openai/gpt-oss-120b",
        embedding_model,
        embedding_base_url="http://embed:80",
        **kwargs,
    )
    provider._client = httpx.Client(transport=httpx.MockTransport(handler))
    return provider


def test_health_reports_unavailable_when_chat_model_is_not_served() -> None:
    provider = _vllm_provider(chat_models=["another/model"])
    health = provider.health()
    assert health.available is False
    assert "openai/gpt-oss-120b" in (health.detail or "")


def test_health_reports_unavailable_when_tei_serves_wrong_model() -> None:
    provider = _vllm_provider(served_embedding_model="BAAI/bge-base-en-v1.5")
    health = provider.health()
    assert health.available is False
    assert "google/embeddinggemma-300m" in (health.detail or "")


def test_health_is_available_when_vllm_and_tei_are_ready() -> None:
    health = _vllm_provider().health()
    assert health.available is True
    assert health.model == "openai/gpt-oss-120b"
    assert health.embedding_model == "google/embeddinggemma-300m"


def test_health_reports_unavailable_when_embedding_width_is_wrong() -> None:
    provider = _vllm_provider(embedding_width=embedding_dimension() + 1)
    health = provider.health()
    assert health.available is False
    assert str(embedding_dimension()) in (health.detail or "")


def test_health_probes_embedding_width_only_once() -> None:
    calls: list[str] = []
    provider = _vllm_provider()
    original_send = provider._client.send

    def recording_send(request: httpx.Request, *args: Any, **kwargs: Any):
        calls.append(request.url.path)
        return original_send(request, *args, **kwargs)

    provider._client.send = recording_send  # type: ignore[method-assign]
    assert provider.health().available is True
    assert provider.health().available is True
    assert calls.count("/v1/embeddings") == 1


def test_chat_sends_vllm_priority_reasoning_and_guided_schema() -> None:
    captured: dict[str, Any] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured.update(json.loads(request.content))
        return httpx.Response(
            200,
            json={
                "choices": [{"message": {"content": "{}"}}],
                "usage": {"prompt_tokens": 1, "completion_tokens": 1},
            },
        )

    provider = _vllm_provider(
        reasoning="low", max_tokens=512, priority=-10, max_parallel=4
    )
    provider._client = httpx.Client(transport=httpx.MockTransport(handler))
    schema = {"type": "object", "properties": {"answer": {"type": "string"}}}
    provider.chat([{"role": "user", "content": "hi"}], schema=schema)

    assert captured["model"] == "openai/gpt-oss-120b"
    assert captured["max_tokens"] == 512
    assert captured["priority"] == -10
    assert captured["reasoning_effort"] == "low"
    assert captured["response_format"]["json_schema"]["strict"] is True
    assert captured["request_id"].startswith("hope-")


def test_chat_omits_reasoning_when_unset() -> None:
    captured: dict[str, Any] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured.update(json.loads(request.content))
        return httpx.Response(
            200,
            json={"choices": [{"message": {"content": "ok"}}], "usage": {}},
        )

    provider = _vllm_provider()
    provider._client = httpx.Client(transport=httpx.MockTransport(handler))
    provider.chat([{"role": "user", "content": "hi"}])
    assert "reasoning_effort" not in captured


def test_chat_records_openai_usage_counters() -> None:
    provider = _vllm_provider()
    labels = ("openai/gpt-oss-120b", WORKLOAD_BATCH, "chat")
    before = telemetry.GENERATED_TOKENS.labels(*labels)._value.get()
    provider.chat([{"role": "user", "content": "hi"}])
    after = telemetry.GENERATED_TOKENS.labels(*labels)._value.get()
    assert after - before == 22


def test_workloads_share_model_but_have_separate_priority_and_budgets() -> None:
    settings = PlatformSettings(
        vllm_base_url="http://vllm:8000",
        vllm_chat_model="openai/gpt-oss-120b",
        embedding_base_url="http://embed:80",
        vllm_max_tokens=2048,
        vllm_interactive_max_tokens=768,
        vllm_batch_reasoning="low",
        vllm_interactive_reasoning="medium",
        vllm_batch_concurrency=4,
        vllm_batch_priority=0,
        vllm_interactive_priority=-10,
    )
    with _patched_settings(settings):
        batch = get_model_provider(WORKLOAD_BATCH)
        interactive = get_model_provider(WORKLOAD_INTERACTIVE)

    assert batch.chat_model == interactive.chat_model == "openai/gpt-oss-120b"
    assert (batch.max_tokens, batch.priority, batch.max_parallel) == (2048, 0, 4)
    assert (interactive.max_tokens, interactive.priority, interactive.max_parallel) == (
        768,
        -10,
        1,
    )
    assert (batch.reasoning, interactive.reasoning) == ("low", "medium")


def test_unconfigured_endpoint_still_yields_disabled_provider() -> None:
    with _patched_settings(PlatformSettings(vllm_base_url="", vllm_chat_model="")):
        assert isinstance(get_model_provider(), DisabledModelProvider)


def test_health_and_openapi_are_available_without_local_ai() -> None:
    client = TestClient(app)
    health = client.get("/health/ready")
    assert health.status_code == 200
    assert health.json()["degraded"] is True

    schema = client.get("/api/openapi.json").json()
    assert "/api/v1/matches" in schema["paths"]
    assert "/internal/v1/webhooks/apify" in schema["paths"]


def test_readiness_checks_shared_model_once() -> None:
    settings = PlatformSettings(
        vllm_base_url="http://vllm:8000",
        vllm_chat_model="openai/gpt-oss-120b",
        embedding_base_url="http://embed:80",
    )
    with _patched_settings(settings):
        with patch.object(
            VllmModelProvider,
            "health",
            autospec=True,
            side_effect=lambda self: ModelHealth(True, "vllm", self.chat_model),
        ) as health:
            payload = TestClient(app).get("/health/ready").json()

    assert health.call_count == 1
    assert set(payload["workloads"]) == {WORKLOAD_BATCH}
    assert payload["degraded"] is False


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
            json={"limit": 25, "max_companies": 3},
            headers=headers,
        )
        assert first.status_code == 200
        assert first.json() == {
            "source": "company_careers",
            "status": "accepted",
            "task_id": "task-abc",
        }
        # max_companies is what actually bounds a crawl; limit only truncates
        # ranked matches, so it must not be mistaken for a fetch bound.
        assert dispatched == [
            (
                "company_careers",
                {"limit": 25, "max_companies": 3, "dry_run": False},
            ),
        ]

        # Replaying the same key returns the stored response without a second run.
        second = client.post(
            "/internal/v1/sources/company_careers/execute",
            json={"limit": 25, "max_companies": 3},
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


def test_rate_limit_fallback_respects_its_entry_ceiling(monkeypatch) -> None:
    """The ceiling exists to bound memory during a Redis outage.

    Evicting only *expired* entries leaves it unenforced in the one case that
    matters: many distinct identities arriving inside a single window, where
    nothing has expired yet.
    """

    def unavailable(_redis_url: str):
        def raise_offline(**_kwargs):
            raise rate_limit.RedisError("offline")

        return raise_offline

    monkeypatch.setattr(rate_limit, "_script", unavailable)
    monkeypatch.setattr(rate_limit, "_FALLBACK_MAX_ENTRIES", 2)
    monkeypatch.setattr(rate_limit, "_fallback", {})

    for index in range(10):
        rate_limit.allow_request(
            bucket="test",
            identity=f"student-{index}@example.edu",
            limit=5,
            window_seconds=600,
            redis_url="redis://offline",
        )

    assert len(rate_limit._fallback) <= 2


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

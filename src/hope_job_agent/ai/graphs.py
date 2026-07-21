"""LangGraph workflows for enrichment, matching, coaching, and market signals.

Each graph that consumes structured model output follows the same shape:

    generate -> validate -> (retry | done)

The validate step parses the reply against the matching model in
:mod:`hope_job_agent.ai.schemas`. A malformed or out-of-contract reply feeds the
validation error back into the next attempt as a correction message, bounded by
``MAX_GENERATION_ATTEMPTS``. Exhausting the attempts routes the item to
``review`` rather than persisting unvalidated model output.

``RetryPolicy`` covers a different failure: a transient provider outage, where
re-prompting is pointless but retrying the call is not.
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from typing import Any, TypedDict

from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.graph import END, START, StateGraph
from langgraph.graph.state import CompiledStateGraph
from langgraph.types import RetryPolicy
from pydantic import BaseModel, ValidationError

from hope_job_agent.ai.provider import ModelProvider, ModelUnavailable
from hope_job_agent.ai.ranking import compose_hybrid_score
from hope_job_agent.ai.schemas import (
    JobEnrichmentPayload,
    MarketSignalsPayload,
    MatchScorePayload,
    json_schema,
)

# One re-prompt. A local model that fails the contract twice is unlikely to
# succeed on a third try, and every attempt costs a full generation.
MAX_GENERATION_ATTEMPTS = 2

# Retries the provider call itself on a transient outage. Distinct from the
# re-prompt cycle, which handles a healthy connection returning bad content.
PROVIDER_RETRY = RetryPolicy(retry_on=(ModelUnavailable,), max_attempts=3)

STATUS_READY = "ready"
STATUS_REVIEW = "review"


class JobEnrichmentState(TypedDict, total=False):
    job_id: str
    title: str
    description: str
    enrichment: dict[str, Any]
    status: str
    error: str
    raw_output: str
    attempts: int


class MatchState(TypedDict, total=False):
    student_id: str
    job_id: str
    rule_score: float
    vector_score: float
    evidence: list[str]
    llm_score: float | None
    final_score: float
    explanation: str
    degraded: bool


class CoachState(TypedDict, total=False):
    user_id: str
    question: str
    context: dict[str, Any]
    response: str
    citations: list[dict[str, str]]
    proposed_action: dict[str, Any] | None


class MarketPulseState(TypedDict, total=False):
    posts: list[dict[str, Any]]
    signals: list[dict[str, Any]]
    rejected: bool
    error: str
    raw_output: str
    attempts: int


def _correction_message(raw_output: str, error: str) -> dict[str, str]:
    """Feed a failed attempt back to the model as a correction turn."""

    return {
        "role": "user",
        "content": (
            "Your previous reply did not satisfy the schema.\n"
            f"Reply was: {raw_output[:2000]}\n"
            f"Problem: {error}\n"
            "Return corrected JSON only."
        ),
    }


def _parse(raw: str, model: type[BaseModel]) -> Any:
    """Parse ``raw`` into ``model``; JSON errors surface as ``ValueError``."""

    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ValueError(f"reply was not valid JSON: {exc}") from exc
    return model.model_validate(data)


def _exhausted(state: JobEnrichmentState | MarketPulseState) -> bool:
    return int(state.get("attempts", 0)) >= MAX_GENERATION_ATTEMPTS


def build_job_enrichment_graph(
    provider: ModelProvider,
    checkpointer: BaseCheckpointSaver[Any] | None = None,
) -> CompiledStateGraph[Any, Any, Any]:
    schema = json_schema(JobEnrichmentPayload)
    system = (
        "Extract only claims directly supported by the job text. "
        "Do not infer sponsorship. Every evidence entry must include a "
        "'quote' field copied verbatim from the posting. "
        "Return JSON matching the schema."
    )

    def generate(state: JobEnrichmentState) -> JobEnrichmentState:
        messages: list[dict[str, str]] = [
            {"role": "system", "content": system},
            {
                "role": "user",
                "content": f"{state['title']}\n\n{state.get('description', '')}",
            },
        ]
        if state.get("error") and state.get("raw_output"):
            messages.append(_correction_message(state["raw_output"], state["error"]))
        try:
            content = provider.chat(messages, schema=schema)
        except ModelUnavailable as exc:
            # Surfaced after RetryPolicy has exhausted its attempts.
            return {
                **state,
                "status": STATUS_REVIEW,
                "error": str(exc),
                "raw_output": "",
                "attempts": MAX_GENERATION_ATTEMPTS,
            }
        return {
            **state,
            "raw_output": content,
            "attempts": int(state.get("attempts", 0)) + 1,
        }

    def validate(state: JobEnrichmentState) -> JobEnrichmentState:
        if state.get("status") == STATUS_REVIEW and not state.get("raw_output"):
            return state
        try:
            payload = _parse(state.get("raw_output", ""), JobEnrichmentPayload)
        except (ValidationError, ValueError) as exc:
            return {**state, "status": STATUS_REVIEW, "error": str(exc)}
        return {
            **state,
            "enrichment": payload.model_dump(mode="json"),
            "status": STATUS_READY,
            "error": "",
        }

    def route(state: JobEnrichmentState) -> str:
        if state.get("status") == STATUS_READY or _exhausted(state):
            return "done"
        return "retry"

    graph = StateGraph(JobEnrichmentState)
    graph.add_node("extract_evidence", generate, retry_policy=PROVIDER_RETRY)
    graph.add_node("validate_evidence", validate)
    graph.add_edge(START, "extract_evidence")
    graph.add_edge("extract_evidence", "validate_evidence")
    graph.add_conditional_edges(
        "validate_evidence", route, {"retry": "extract_evidence", "done": END}
    )
    return graph.compile(checkpointer=checkpointer)


def build_match_generation_graph(
    provider: ModelProvider,
    checkpointer: BaseCheckpointSaver[Any] | None = None,
) -> CompiledStateGraph[Any, Any, Any]:
    schema = json_schema(MatchScorePayload)

    def rerank(state: MatchState) -> MatchState:
        try:
            content = provider.chat(
                [
                    {
                        "role": "system",
                        "content": (
                            "Score fit from 0 to 1 using only supplied evidence."
                        ),
                    },
                    {"role": "user", "content": "\n".join(state.get("evidence", []))},
                ],
                schema=schema,
            )
            llm_score: float | None = _parse(content, MatchScorePayload).score
        except (ModelUnavailable, ValidationError, ValueError):
            # A missing LLM opinion is a supported state: compose_hybrid_score
            # reweights onto the deterministic and vector signals and marks the
            # result degraded.
            llm_score = None
        score = compose_hybrid_score(
            rule_score=state["rule_score"],
            vector_score=state["vector_score"],
            llm_score=llm_score,
        )
        evidence = state.get("evidence", [])[:3]
        explanation = "; ".join(evidence) if evidence else "General profile relevance"
        return {
            **state,
            "llm_score": llm_score,
            "final_score": score.final,
            "degraded": score.degraded,
            "explanation": explanation,
        }

    graph = StateGraph(MatchState)
    graph.add_node("evidence_rerank", rerank)
    graph.add_edge(START, "evidence_rerank")
    graph.add_edge("evidence_rerank", END)
    return graph.compile(checkpointer=checkpointer)


COACH_SYSTEM_PROMPT = (
    "You are an advisory career coach. Use only the "
    "supplied student and job context. Never claim to "
    "apply, send, contact, or change data. Mark suggestions "
    "clearly and cite job IDs when relevant."
)

COACH_UNAVAILABLE = (
    "Local coaching is temporarily unavailable. Your saved matches and "
    "application tracker are still available."
)


def coach_messages(question: str, context: dict[str, Any]) -> list[dict[str, str]]:
    """Build the coach prompt shared by the graph and the streaming route."""

    serialized = json.dumps(context or {}, default=str)[:24000]
    return [
        {"role": "system", "content": COACH_SYSTEM_PROMPT},
        {"role": "user", "content": f"Context: {serialized}\nQuestion: {question}"},
    ]


def stream_coach_reply(
    provider: ModelProvider, question: str, context: dict[str, Any]
) -> Iterator[str]:
    """Yield coach tokens as the model produces them.

    Emits the unavailable notice if the provider is down or drops mid-reply, so
    the caller sees the same copy regardless of when the outage lands.
    """

    produced = False
    try:
        for chunk in provider.stream_chat(coach_messages(question, context)):
            produced = True
            yield chunk
    except ModelUnavailable:
        if not produced:
            yield COACH_UNAVAILABLE
        return
    if not produced:
        yield COACH_UNAVAILABLE


def build_career_coach_graph(
    provider: ModelProvider,
    checkpointer: BaseCheckpointSaver[Any] | None = None,
) -> CompiledStateGraph[Any, Any, Any]:
    def answer(state: CoachState) -> CoachState:
        try:
            response = provider.chat(
                coach_messages(state["question"], state.get("context", {})),
                temperature=0.2,
            )
        except ModelUnavailable:
            response = COACH_UNAVAILABLE
        return {**state, "response": response, "proposed_action": None}

    graph = StateGraph(CoachState)
    graph.add_node("advisory_answer", answer)
    graph.add_edge(START, "advisory_answer")
    graph.add_edge("advisory_answer", END)
    return graph.compile(checkpointer=checkpointer)


def build_market_pulse_graph(
    provider: ModelProvider,
    checkpointer: BaseCheckpointSaver[Any] | None = None,
) -> CompiledStateGraph[Any, Any, Any]:
    schema = json_schema(MarketSignalsPayload)
    system = (
        "Create time-bounded hiring signals supported by the posts. "
        "Each signal must cite one or more source_url values."
    )

    def guard(state: MarketPulseState) -> MarketPulseState:
        """Reject the batch outright if any post arrived without provenance."""

        posts = state.get("posts", [])
        if not posts or any(not post.get("source_url") for post in posts):
            return {**state, "signals": [], "rejected": True, "error": ""}
        return {**state, "rejected": False}

    def generate(state: MarketPulseState) -> MarketPulseState:
        messages: list[dict[str, str]] = [
            {"role": "system", "content": system},
            {
                "role": "user",
                "content": json.dumps(state.get("posts", []), default=str)[:30000],
            },
        ]
        if state.get("error") and state.get("raw_output"):
            messages.append(_correction_message(state["raw_output"], state["error"]))
        try:
            content = provider.chat(messages, schema=schema)
        except ModelUnavailable as exc:
            return {
                **state,
                "signals": [],
                "rejected": True,
                "error": str(exc),
                "raw_output": "",
                "attempts": MAX_GENERATION_ATTEMPTS,
            }
        return {
            **state,
            "raw_output": content,
            "attempts": int(state.get("attempts", 0)) + 1,
        }

    def validate(state: MarketPulseState) -> MarketPulseState:
        if not state.get("raw_output"):
            return state
        try:
            payload = _parse(state.get("raw_output", ""), MarketSignalsPayload)
        except (ValidationError, ValueError) as exc:
            return {**state, "signals": [], "rejected": True, "error": str(exc)}
        # The model may only cite posts it was actually shown. This is the
        # compliance boundary, so it is enforced here rather than in the schema.
        valid_urls = {
            post["source_url"]
            for post in state.get("posts", [])
            if post.get("source_url")
        }
        cited = [
            signal.model_dump(mode="json")
            for signal in payload.signals
            if set(signal.citations).issubset(valid_urls)
        ]
        if not cited:
            return {
                **state,
                "signals": [],
                "rejected": True,
                "error": "no signal cited a supplied source_url",
            }
        return {**state, "signals": cited, "rejected": False, "error": ""}

    def route(state: MarketPulseState) -> str:
        if not state.get("rejected") or _exhausted(state):
            return "done"
        return "retry"

    graph = StateGraph(MarketPulseState)
    graph.add_node("check_provenance", guard)
    graph.add_node("extract_cited_signals", generate, retry_policy=PROVIDER_RETRY)
    graph.add_node("validate_citations", validate)
    graph.add_edge(START, "check_provenance")
    graph.add_conditional_edges(
        "check_provenance",
        lambda state: "reject" if state.get("rejected") else "extract",
        {"reject": END, "extract": "extract_cited_signals"},
    )
    graph.add_edge("extract_cited_signals", "validate_citations")
    graph.add_conditional_edges(
        "validate_citations", route, {"retry": "extract_cited_signals", "done": END}
    )
    return graph.compile(checkpointer=checkpointer)

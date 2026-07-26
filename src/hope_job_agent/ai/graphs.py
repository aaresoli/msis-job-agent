"""LangGraph workflows for enrichment, matching, coaching, and market signals.

Each graph that consumes structured model output follows the same shape:

    generate -> validate -> (retry | done)

The validate step parses the reply against the matching model in
:mod:`hope_job_agent.ai.schemas`. A malformed or out-of-contract reply feeds the
validation error back into the next attempt as a correction message, bounded by
``MAX_GENERATION_ATTEMPTS``. Exhausting the attempts routes the item to
``review`` rather than persisting unvalidated model output.

``_chat_with_retry`` covers a different failure: a transient provider outage,
where re-prompting is pointless but retrying the call is not.
"""

from __future__ import annotations

import json
import time
from collections.abc import Iterable, Iterator
from dataclasses import dataclass
from typing import Any, TypedDict

from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.graph import END, START, StateGraph
from langgraph.graph.state import CompiledStateGraph
from pydantic import BaseModel, ValidationError

from hope_job_agent.ai.provider import ModelProvider, ModelUnavailable
from hope_job_agent.ai.ranking import compose_hybrid_score
from hope_job_agent.ai.schemas import (
    EvidenceItem,
    JobEnrichmentPayload,
    MarketSignalsPayload,
    MatchScorePayload,
    ResumeProfilePayload,
    json_schema,
)

# One re-prompt. A local model that fails the contract twice is unlikely to
# succeed on a third try, and every attempt costs a full generation.
MAX_GENERATION_ATTEMPTS = 2

# Retries the provider call itself on a transient outage. Distinct from the
# re-prompt cycle, which handles a healthy connection returning bad content.
PROVIDER_MAX_ATTEMPTS = 3
PROVIDER_RETRY_BACKOFF_SECONDS = 0.25

STATUS_READY = "ready"
STATUS_REVIEW = "review"
# Distinct from ``review``: nothing is wrong with the input, the model simply
# was not reachable. Resume parsing retries these rather than asking a human to
# look at a document the system never actually read.
STATUS_UNAVAILABLE = "awaiting_local_ai"


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
    # The posting and the student, as the model needs to see them. Without
    # these the reranker is scoring the deterministic rubric's own summary of
    # itself rather than the fit.
    job: dict[str, Any]
    student: dict[str, Any]
    llm_score: float | None
    final_score: float
    explanation: str
    degraded: bool


class ResumeParseState(TypedDict, total=False):
    resume_text: str
    profile: dict[str, Any]
    status: str
    error: str
    raw_output: str
    attempts: int


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


def _chat_with_retry(
    provider: ModelProvider, messages: list[dict[str, str]], *, schema: dict[str, Any]
) -> str:
    """Call the provider, retrying a transient outage before giving up.

    LangGraph's ``RetryPolicy`` cannot do this job here. It only retries
    exceptions that *escape* a node, and these graphs must catch
    ``ModelUnavailable`` in-node to degrade toward ``review`` rather than raise
    out of ``invoke``. A node that both catches and declares a retry policy
    silently gets one attempt, so the retry lives at the call site instead.
    """

    last_error: ModelUnavailable | None = None
    for attempt in range(1, PROVIDER_MAX_ATTEMPTS + 1):
        try:
            return provider.chat(messages, schema=schema)
        except ModelUnavailable as exc:
            last_error = exc
            if attempt < PROVIDER_MAX_ATTEMPTS:
                time.sleep(PROVIDER_RETRY_BACKOFF_SECONDS * attempt)
    assert last_error is not None  # every path above either returned or set it
    raise last_error


def _parse(raw: str, model: type[BaseModel]) -> Any:
    """Parse ``raw`` into ``model``; JSON errors surface as ``ValueError``."""

    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ValueError(f"reply was not valid JSON: {exc}") from exc
    return model.model_validate(data)


def _normalize_for_quote_match(text: str) -> str:
    """Collapse whitespace and case so only the wording has to match."""

    return " ".join(text.split()).casefold()


def _quotes_absent_from(source_text: str, items: Iterable[EvidenceItem]) -> list[str]:
    """Return every quote in ``items`` that does not appear in ``source_text``.

    The schema can only require that a quote is non-empty; it never sees the
    source. Without this check "verbatim" is a request in the system prompt
    rather than a guarantee, and a fabricated quote validates cleanly.
    """

    haystack = _normalize_for_quote_match(source_text)
    return [
        item.quote
        for item in items
        if _normalize_for_quote_match(item.quote) not in haystack
    ]


def _unsupported_quotes(
    payload: JobEnrichmentPayload, description: str, title: str
) -> list[str]:
    """Return every evidence quote absent from the posting text.

    Sponsorship, salary, and location are exactly the claims the project
    promises are traceable, so an unsupported quote fails the payload.
    """

    return _quotes_absent_from(
        f"{title}\n{description}",
        [
            item
            for group in (
                payload.work_auth_evidence,
                payload.salary_evidence,
                payload.location_evidence,
            )
            for item in group
        ],
    )


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
            content = _chat_with_retry(provider, messages, schema=schema)
        except ModelUnavailable as exc:
            # Surfaced only after PROVIDER_MAX_ATTEMPTS calls have all failed.
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
        unsupported = _unsupported_quotes(
            payload, state.get("description", ""), state.get("title", "")
        )
        if unsupported:
            return {
                **state,
                "status": STATUS_REVIEW,
                "error": (
                    "evidence quote not found in the posting: "
                    + "; ".join(repr(quote) for quote in unsupported[:3])
                ),
            }
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
    graph.add_node("extract_evidence", generate)
    graph.add_node("validate_evidence", validate)
    graph.add_edge(START, "extract_evidence")
    graph.add_edge("extract_evidence", "validate_evidence")
    graph.add_conditional_edges(
        "validate_evidence", route, {"retry": "extract_evidence", "done": END}
    )
    return graph.compile(checkpointer=checkpointer)


RESUME_SYSTEM_PROMPT = (
    "Extract a proposed student profile using only resume evidence. "
    "Do not infer work authorization, citizenship, age, or any other private "
    "attribute, even if the resume hints at it. Every evidence entry must "
    "include a 'quote' field copied verbatim from the resume. "
    "Return JSON matching the schema."
)


def build_resume_parse_graph(
    provider: ModelProvider,
    checkpointer: BaseCheckpointSaver[Any] | None = None,
) -> CompiledStateGraph[Any, Any, Any]:
    """Extract a draft profile from resume text under the usual validate loop.

    This path used to hand-roll its own JSON Schema and accept whatever
    ``json.loads`` returned, so a reply that parsed as JSON was persisted even
    if it had no skills, invented quotes, or the wrong shape entirely. It now
    shares the contract-and-correction cycle every other extraction uses.
    """

    schema = json_schema(ResumeProfilePayload)

    def generate(state: ResumeParseState) -> ResumeParseState:
        messages: list[dict[str, str]] = [
            {"role": "system", "content": RESUME_SYSTEM_PROMPT},
            {"role": "user", "content": state.get("resume_text", "")},
        ]
        if state.get("error") and state.get("raw_output"):
            messages.append(_correction_message(state["raw_output"], state["error"]))
        try:
            content = _chat_with_retry(provider, messages, schema=schema)
        except ModelUnavailable as exc:
            return {
                **state,
                "status": STATUS_UNAVAILABLE,
                "error": str(exc),
                "raw_output": "",
                "attempts": MAX_GENERATION_ATTEMPTS,
            }
        return {
            **state,
            "raw_output": content,
            "attempts": int(state.get("attempts", 0)) + 1,
        }

    def validate(state: ResumeParseState) -> ResumeParseState:
        if state.get("status") == STATUS_UNAVAILABLE:
            return state
        try:
            payload = _parse(state.get("raw_output", ""), ResumeProfilePayload)
        except (ValidationError, ValueError) as exc:
            return {**state, "status": STATUS_REVIEW, "error": str(exc)}
        unsupported = _quotes_absent_from(
            state.get("resume_text", ""), payload.evidence
        )
        if unsupported:
            return {
                **state,
                "status": STATUS_REVIEW,
                "error": (
                    "evidence quote not found in the resume: "
                    + "; ".join(repr(quote) for quote in unsupported[:3])
                ),
            }
        return {
            **state,
            "profile": payload.model_dump(mode="json"),
            "status": STATUS_READY,
            "error": "",
        }

    def route(state: ResumeParseState) -> str:
        if state.get("status") in (STATUS_READY, STATUS_UNAVAILABLE):
            return "done"
        if int(state.get("attempts", 0)) >= MAX_GENERATION_ATTEMPTS:
            return "done"
        return "retry"

    graph = StateGraph(ResumeParseState)
    graph.add_node("extract_profile", generate)
    graph.add_node("validate_profile", validate)
    graph.add_edge(START, "extract_profile")
    graph.add_edge("extract_profile", "validate_profile")
    graph.add_conditional_edges(
        "validate_profile", route, {"retry": "extract_profile", "done": END}
    )
    return graph.compile(checkpointer=checkpointer)


def _deterministic_explanation(state: MatchState) -> str:
    """Explain a match from the rubric alone, for when the model is down."""

    evidence = state.get("evidence", [])[:3]
    return "; ".join(evidence) if evidence else "General profile relevance"


MATCH_SYSTEM_PROMPT = (
    "You judge how well one job posting fits one graduate student. "
    "Use only the supplied posting and profile. "
    "Score 0 to 1, where 1 is an excellent fit for this student specifically. "
    "Weigh role and responsibilities against the student's target roles and "
    "skills, then seniority against their academic stage, then location "
    "against their stated preferences. "
    "Do not reward a posting for being prestigious, and do not infer work "
    "authorization or sponsorship. "
    "Give a reason of at most two sentences, addressed to the student, "
    "naming the specific evidence that drove the score."
)


def _match_prompt(state: MatchState) -> str:
    """Render the posting and the profile the model has to judge."""

    return json.dumps(
        {
            "student": state.get("student", {}),
            "job": state.get("job", {}),
            "deterministic_signals": state.get("evidence", []),
        },
        default=str,
    )[:24000]


def build_match_generation_graph(
    provider: ModelProvider,
    checkpointer: BaseCheckpointSaver[Any] | None = None,
) -> CompiledStateGraph[Any, Any, Any]:
    schema = json_schema(MatchScorePayload)

    def rerank(state: MatchState) -> MatchState:
        reason = ""
        try:
            content = provider.chat(
                [
                    {"role": "system", "content": MATCH_SYSTEM_PROMPT},
                    {"role": "user", "content": _match_prompt(state)},
                ],
                schema=schema,
            )
            payload = _parse(content, MatchScorePayload)
            llm_score: float | None = payload.score
            reason = payload.reason
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
        return {
            **state,
            "llm_score": llm_score,
            "final_score": score.final,
            "degraded": score.degraded,
            # The model's reason when there is one. The deterministic reasons
            # are the fallback, and they read as a fallback: they restate the
            # rubric that produced the score rather than explaining the fit.
            "explanation": reason or _deterministic_explanation(state),
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
    "clearly. "
    # The context now actually contains postings, so this is a checkable
    # instruction rather than a request the model could only satisfy by
    # inventing an ID: every job_id in the reply is matched back against what
    # was supplied before anything is stored as a citation.
    "When you refer to a specific posting, quote its job_id exactly as it "
    "appears in the context. Never cite a job_id that is not in the context, "
    "and say so plainly when the context does not answer the question."
)

COACH_UNAVAILABLE = (
    "Local coaching is temporarily unavailable. Your saved matches and "
    "application tracker are still available."
)

COACH_TRUNCATED_NOTICE = (
    "\n\n[This answer stopped early because local coaching became "
    "unavailable mid-reply. Ask again for a complete response.]"
)


def coach_messages(question: str, context: dict[str, Any]) -> list[dict[str, str]]:
    """Build the coach prompt shared by the graph and the streaming route."""

    serialized = json.dumps(context or {}, default=str)[:24000]
    return [
        {"role": "system", "content": COACH_SYSTEM_PROMPT},
        {"role": "user", "content": f"Context: {serialized}\nQuestion: {question}"},
    ]


@dataclass
class CoachStreamStatus:
    """Whether a coach stream finished cleanly.

    ``stream_coach_reply`` cannot signal a mid-stream failure through its return
    value, because by then it has already yielded tokens the caller forwarded to
    the browser. Callers that persist the turn pass one of these in and check it
    before treating the accumulated text as a complete answer.
    """

    truncated: bool = False


def stream_coach_reply(
    provider: ModelProvider,
    question: str,
    context: dict[str, Any],
    status: CoachStreamStatus | None = None,
) -> Iterator[str]:
    """Yield coach tokens as the model produces them.

    Emits the unavailable notice if the provider is down before producing
    anything. An outage that lands *after* some tokens have shipped is a
    different case: the student is already looking at a partial answer, so
    deleting it is as confusing as keeping it. The remainder is marked inline
    and flagged on ``status`` so the caller does not store it as a whole turn.
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
        if status is not None:
            status.truncated = True
        yield COACH_TRUNCATED_NOTICE
        return
    if not produced:
        yield COACH_UNAVAILABLE


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
            content = _chat_with_retry(provider, messages, schema=schema)
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
    graph.add_node("extract_cited_signals", generate)
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

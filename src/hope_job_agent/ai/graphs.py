"""LangGraph workflows for enrichment, matching, coaching, and market signals."""

from __future__ import annotations

import json
from typing import Any, TypedDict

from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.graph import END, START, StateGraph

from hope_job_agent.ai.provider import ModelProvider, ModelUnavailable
from hope_job_agent.ai.ranking import compose_hybrid_score


class JobEnrichmentState(TypedDict, total=False):
    job_id: str
    title: str
    description: str
    enrichment: dict[str, Any]
    status: str
    error: str


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


def build_job_enrichment_graph(
    provider: ModelProvider, checkpointer: BaseCheckpointSaver | None = None
):
    def enrich(state: JobEnrichmentState) -> JobEnrichmentState:
        schema = {
            "type": "object",
            "properties": {
                "skills": {"type": "array", "items": {"type": "string"}},
                "requirements": {"type": "array", "items": {"type": "string"}},
                "work_auth_evidence": {"type": "array", "items": {"type": "object"}},
                "salary_evidence": {"type": "array", "items": {"type": "object"}},
                "location_evidence": {"type": "array", "items": {"type": "object"}},
                "confidence": {"type": "number"},
            },
            "required": [
                "skills",
                "requirements",
                "work_auth_evidence",
                "salary_evidence",
                "location_evidence",
                "confidence",
            ],
        }
        try:
            content = provider.chat(
                [
                    {
                        "role": "system",
                        "content": (
                            "Extract only claims directly supported by the job text. "
                            "Do not infer sponsorship. Return JSON matching the schema."
                        ),
                    },
                    {
                        "role": "user",
                        "content": f"{state['title']}\n\n{state['description']}",
                    },
                ],
                schema=schema,
            )
            parsed = json.loads(content)
            return {**state, "enrichment": parsed, "status": "ready"}
        except (ModelUnavailable, json.JSONDecodeError, KeyError, TypeError) as exc:
            return {**state, "status": "review", "error": str(exc)}

    graph = StateGraph(JobEnrichmentState)
    graph.add_node("extract_evidence", enrich)
    graph.add_edge(START, "extract_evidence")
    graph.add_edge("extract_evidence", END)
    return graph.compile(checkpointer=checkpointer)


def build_match_generation_graph(
    provider: ModelProvider, checkpointer: BaseCheckpointSaver | None = None
):
    def rerank(state: MatchState) -> MatchState:
        try:
            content = provider.chat(
                [
                    {
                        "role": "system",
                        "content": (
                            "Score fit from 0 to 1 using only supplied " "evidence."
                        ),
                    },
                    {"role": "user", "content": "\n".join(state.get("evidence", []))},
                ],
                schema={
                    "type": "object",
                    "properties": {"score": {"type": "number"}},
                    "required": ["score"],
                },
            )
            llm_score = float(json.loads(content)["score"])
        except (
            ModelUnavailable,
            ValueError,
            KeyError,
            TypeError,
            json.JSONDecodeError,
        ):
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


def build_career_coach_graph(
    provider: ModelProvider, checkpointer: BaseCheckpointSaver | None = None
):
    def answer(state: CoachState) -> CoachState:
        context = json.dumps(state.get("context", {}), default=str)[:24000]
        try:
            response = provider.chat(
                [
                    {
                        "role": "system",
                        "content": (
                            "You are an advisory career coach. Use only the "
                            "supplied student and job context. Never claim to "
                            "apply, send, contact, or change data. Mark suggestions "
                            "clearly and cite job IDs when relevant."
                        ),
                    },
                    {
                        "role": "user",
                        "content": f"Context: {context}\nQuestion: {state['question']}",
                    },
                ],
                temperature=0.2,
            )
        except ModelUnavailable:
            response = (
                "Local coaching is temporarily unavailable. Your saved matches and "
                "application tracker are still available."
            )
        return {**state, "response": response, "proposed_action": None}

    graph = StateGraph(CoachState)
    graph.add_node("advisory_answer", answer)
    graph.add_edge(START, "advisory_answer")
    graph.add_edge("advisory_answer", END)
    return graph.compile(checkpointer=checkpointer)


def build_market_pulse_graph(
    provider: ModelProvider, checkpointer: BaseCheckpointSaver | None = None
):
    def extract(state: MarketPulseState) -> MarketPulseState:
        posts = state.get("posts", [])
        if not posts or any(not post.get("source_url") for post in posts):
            return {**state, "signals": [], "rejected": True}
        try:
            content = provider.chat(
                [
                    {
                        "role": "system",
                        "content": (
                            "Create time-bounded hiring signals supported by "
                            "the posts. "
                            "Each signal must cite one or more source_url values."
                        ),
                    },
                    {"role": "user", "content": json.dumps(posts, default=str)[:30000]},
                ],
                schema={
                    "type": "object",
                    "properties": {
                        "signals": {"type": "array", "items": {"type": "object"}}
                    },
                    "required": ["signals"],
                },
            )
            signals = json.loads(content).get("signals", [])
        except (ModelUnavailable, json.JSONDecodeError, TypeError):
            return {**state, "signals": [], "rejected": True}
        valid_urls = {post["source_url"] for post in posts}
        cited = [
            signal
            for signal in signals
            if signal.get("citations") and set(signal["citations"]).issubset(valid_urls)
        ]
        return {**state, "signals": cited, "rejected": not bool(cited)}

    graph = StateGraph(MarketPulseState)
    graph.add_node("extract_cited_signals", extract)
    graph.add_edge(START, "extract_cited_signals")
    graph.add_edge("extract_cited_signals", END)
    return graph.compile(checkpointer=checkpointer)

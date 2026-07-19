"""Hybrid score composition for deterministic, vector, and LLM signals."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class HybridScore:
    final: float
    rule: float
    vector: float
    llm: float | None
    degraded: bool


def normalize_rule_score(score: float, maximum: float = 20.0) -> float:
    if maximum <= 0:
        raise ValueError("maximum must be positive")
    return max(0.0, min(1.0, score / maximum))


def compose_hybrid_score(
    *, rule_score: float, vector_score: float, llm_score: float | None
) -> HybridScore:
    rule = normalize_rule_score(rule_score)
    vector = max(0.0, min(1.0, vector_score))
    if llm_score is None:
        final = (0.5625 * rule) + (0.4375 * vector)
        return HybridScore(final * 100, rule, vector, None, True)
    llm = max(0.0, min(1.0, llm_score))
    final = (0.45 * rule) + (0.35 * vector) + (0.20 * llm)
    return HybridScore(final * 100, rule, vector, llm, False)

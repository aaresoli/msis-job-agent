"""Hybrid score composition for deterministic, vector, and LLM signals.

The blend lives in ``data/hybrid_weights.json`` rather than in code, matching
how the deterministic rubric is configured in ``data/ranking_weights.json``
(see :mod:`hope_job_agent.scoring.ranker`).

When the local model is unavailable the LLM weight is redistributed across the
remaining signals in proportion to their configured weights, so the degraded
blend is *derived* from the primary one. Both were previously hard-coded, which
let them drift apart silently.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, fields
from functools import lru_cache
from pathlib import Path

DEFAULT_HYBRID_WEIGHTS_PATH = (
    Path(__file__).resolve().parents[3] / "data" / "hybrid_weights.json"
)

# Rubric scores are summed points, not a 0..1 fraction; this divisor maps them
# onto the unit interval the blend expects.
DEFAULT_RULE_SCORE_MAXIMUM = 20.0

_WEIGHT_SUM_TOLERANCE = 1e-6


class HybridWeightsConfigError(ValueError):
    """Raised when a hybrid-weights config file is invalid."""


@dataclass(frozen=True)
class HybridWeights:
    """Relative contribution of each signal to the final match score."""

    rule: float = 0.45
    vector: float = 0.35
    llm: float = 0.20

    def __post_init__(self) -> None:
        for field in fields(self):
            value = getattr(self, field.name)
            if value < 0:
                raise HybridWeightsConfigError(
                    f"Hybrid weight {field.name!r} must not be negative: {value}"
                )
        total = self.rule + self.vector + self.llm
        if abs(total - 1.0) > _WEIGHT_SUM_TOLERANCE:
            raise HybridWeightsConfigError(
                f"Hybrid weights must sum to 1.0, got {total}"
            )

    def without_llm(self) -> tuple[float, float]:
        """Return (rule, vector) renormalized to sum to 1.0.

        Used when the local model is unavailable, so the deterministic and
        vector signals absorb the LLM's share in proportion to their own.
        """

        remaining = self.rule + self.vector
        if remaining <= 0:
            raise HybridWeightsConfigError(
                "Hybrid weights leave no non-LLM signal to fall back on"
            )
        return self.rule / remaining, self.vector / remaining


DEFAULT_HYBRID_WEIGHTS = HybridWeights()


def load_hybrid_weights(
    path: str | Path = DEFAULT_HYBRID_WEIGHTS_PATH,
) -> HybridWeights:
    """Load a hybrid-weights config file, mirroring ``load_ranking_weights``."""

    config_path = Path(path)
    try:
        payload = json.loads(config_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise HybridWeightsConfigError(
            f"Hybrid weights config is not valid JSON: {config_path}: {exc.msg}"
        ) from exc
    except OSError as exc:
        raise HybridWeightsConfigError(
            f"Hybrid weights config could not be read: {config_path}: {exc}"
        ) from exc

    if not isinstance(payload, dict):
        raise HybridWeightsConfigError(
            f"Hybrid weights config must be a JSON object: {config_path}"
        )

    weight_names = {field.name for field in fields(HybridWeights)}
    missing = sorted(weight_names - set(payload))
    extra = sorted(set(payload) - weight_names)
    if missing or extra:
        details = []
        if missing:
            details.append(f"missing={missing}")
        if extra:
            details.append(f"extra={extra}")
        raise HybridWeightsConfigError(
            "Hybrid weights config keys do not match the blend: " + ", ".join(details)
        )

    try:
        values = {key: float(payload[key]) for key in weight_names}
    except (TypeError, ValueError) as exc:
        raise HybridWeightsConfigError(
            f"Hybrid weights config values must be numeric: {config_path}"
        ) from exc

    return HybridWeights(**values)


@lru_cache
def active_hybrid_weights() -> HybridWeights:
    """Return the configured blend, falling back to the built-in defaults.

    Scoring must not fail because an operator mistyped a config file, so an
    unreadable or invalid file degrades to the documented defaults.
    """

    try:
        return load_hybrid_weights()
    except HybridWeightsConfigError:
        return DEFAULT_HYBRID_WEIGHTS


@dataclass(frozen=True)
class HybridScore:
    final: float
    rule: float
    vector: float
    llm: float | None
    degraded: bool


def normalize_rule_score(
    score: float, maximum: float = DEFAULT_RULE_SCORE_MAXIMUM
) -> float:
    if maximum <= 0:
        raise ValueError("maximum must be positive")
    return max(0.0, min(1.0, score / maximum))


def compose_hybrid_score(
    *,
    rule_score: float,
    vector_score: float,
    llm_score: float | None,
    weights: HybridWeights | None = None,
) -> HybridScore:
    blend = weights or active_hybrid_weights()
    rule = normalize_rule_score(rule_score)
    vector = max(0.0, min(1.0, vector_score))
    if llm_score is None:
        rule_weight, vector_weight = blend.without_llm()
        final = (rule_weight * rule) + (vector_weight * vector)
        return HybridScore(final * 100, rule, vector, None, True)
    llm = max(0.0, min(1.0, llm_score))
    final = (blend.rule * rule) + (blend.vector * vector) + (blend.llm * llm)
    return HybridScore(final * 100, rule, vector, llm, False)

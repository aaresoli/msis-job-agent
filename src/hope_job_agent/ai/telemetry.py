"""Per-call metrics for local inference.

vLLM (OpenAI-compatible) returns ``usage.prompt_tokens`` /
``usage.completion_tokens``. The counters stay provider-agnostic so Prometheus
dashboards do not care which engine produced them.

Counters rather than gauges: workers are forked processes that come and go, and
a rate over a counter survives that. Throughput is derived at query time as
``generated_tokens_total / eval_seconds_total`` when eval time is present.
"""

from __future__ import annotations

import logging
from typing import Any

from prometheus_client import Counter

LOGGER = logging.getLogger(__name__)

_LABELS = ("model", "workload", "operation")

REQUESTS = Counter(
    "hope_llm_requests_total",
    "Local model calls, by outcome.",
    (*_LABELS, "outcome"),
)
PROMPT_TOKENS = Counter(
    "hope_llm_prompt_tokens_total",
    "Tokens consumed during prefill.",
    _LABELS,
)
GENERATED_TOKENS = Counter(
    "hope_llm_generated_tokens_total",
    "Tokens produced during decode.",
    _LABELS,
)
EVAL_SECONDS = Counter(
    "hope_llm_eval_seconds_total",
    "Wall-clock seconds spent in decode when the engine reports it. "
    "Divide generated tokens by this for sustained tok/s.",
    _LABELS,
)
LOAD_SECONDS = Counter(
    "hope_llm_load_seconds_total",
    "Wall-clock seconds spent loading model weights when reported. "
    "Sustained non-zero growth means the engine is reloading between calls.",
    _LABELS,
)


def _usage_tokens(payload: dict[str, Any]) -> tuple[int, int]:
    """Read prompt/completion counts from OpenAI-style or legacy bodies."""

    usage = payload.get("usage")
    if isinstance(usage, dict):
        prompt = int(usage.get("prompt_tokens") or 0)
        completion = usage.get("completion_tokens")
        if completion is None and usage.get("total_tokens") is not None:
            completion = int(usage["total_tokens"]) - prompt
        return prompt, int(completion or 0)
    # Legacy field names, kept so older fixtures still record cleanly.
    return (
        int(payload.get("prompt_eval_count") or 0),
        int(payload.get("eval_count") or 0),
    )


def record_call(
    payload: dict[str, Any],
    *,
    model: str,
    workload: str,
    operation: str,
) -> None:
    """Record one completed call from a raw engine response body.

    Never raises: telemetry must not be able to fail a student's request. A
    reply missing the counters (a mocked transport, or a future server version)
    is still counted as a request.
    """

    labels = (model, workload, operation)
    try:
        REQUESTS.labels(*labels, "ok").inc()
        prompt_tokens, generated_tokens = _usage_tokens(payload)
        # OpenAI bodies do not report decode wall time; leave eval at 0 unless
        # a legacy engine included it.
        nano = 1_000_000_000.0
        eval_seconds = float(payload.get("eval_duration") or 0) / nano
        load_seconds = float(payload.get("load_duration") or 0) / nano

        PROMPT_TOKENS.labels(*labels).inc(prompt_tokens)
        GENERATED_TOKENS.labels(*labels).inc(max(0, generated_tokens))
        EVAL_SECONDS.labels(*labels).inc(eval_seconds)
        LOAD_SECONDS.labels(*labels).inc(load_seconds)

        LOGGER.info(
            "local inference model=%s workload=%s op=%s prompt_tokens=%d "
            "generated_tokens=%d tok_per_s=%.1f load_s=%.2f",
            model,
            workload,
            operation,
            prompt_tokens,
            max(0, generated_tokens),
            (
                max(0, generated_tokens) / eval_seconds
                if eval_seconds > 0
                else 0.0
            ),
            load_seconds,
        )
    except (TypeError, ValueError):
        LOGGER.debug("Could not record inference metrics", exc_info=True)


def record_failure(*, model: str, workload: str, operation: str) -> None:
    """Count a call that never produced a usable reply."""

    try:
        REQUESTS.labels(model, workload, operation, "error").inc()
    except ValueError:  # pragma: no cover - label cardinality is fixed above
        LOGGER.debug("Could not record inference failure", exc_info=True)


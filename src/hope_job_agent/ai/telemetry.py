"""Per-call metrics for local inference.

Ollama returns the numbers that decide whether the Spark is being used well --
``prompt_eval_count``, ``eval_count``, ``eval_duration``, ``load_duration`` --
on every non-streaming reply. The provider used to read ``message.content`` and
drop the rest, so there was no way to tell a saturated GPU from an idle one, or
a warm queue from one silently reloading a 65GB model between tasks.

Counters rather than gauges: workers are forked processes that come and go, and
a rate over a counter survives that. Throughput is derived at query time as
``generated_tokens_total / eval_seconds_total``.
"""

from __future__ import annotations

import logging
from typing import Any

from prometheus_client import Counter

LOGGER = logging.getLogger(__name__)

# Ollama reports durations in nanoseconds.
_NANOSECONDS = 1_000_000_000.0

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
    "Wall-clock seconds spent in decode. Divide generated tokens by this "
    "for sustained tok/s.",
    _LABELS,
)
LOAD_SECONDS = Counter(
    "hope_llm_load_seconds_total",
    "Wall-clock seconds spent loading model weights. Sustained non-zero "
    "growth means models are being evicted -- check OLLAMA_MAX_LOADED_MODELS.",
    _LABELS,
)


def record_call(
    payload: dict[str, Any],
    *,
    model: str,
    workload: str,
    operation: str,
) -> None:
    """Record one completed call from a raw Ollama response body.

    Never raises: telemetry must not be able to fail a student's request. A
    reply missing the counters (a mocked transport, or a future server version)
    is still counted as a request.
    """

    labels = (model, workload, operation)
    try:
        REQUESTS.labels(*labels, "ok").inc()
        prompt_tokens = int(payload.get("prompt_eval_count") or 0)
        generated_tokens = int(payload.get("eval_count") or 0)
        eval_seconds = float(payload.get("eval_duration") or 0) / _NANOSECONDS
        load_seconds = float(payload.get("load_duration") or 0) / _NANOSECONDS

        PROMPT_TOKENS.labels(*labels).inc(prompt_tokens)
        GENERATED_TOKENS.labels(*labels).inc(generated_tokens)
        EVAL_SECONDS.labels(*labels).inc(eval_seconds)
        LOAD_SECONDS.labels(*labels).inc(load_seconds)

        LOGGER.info(
            "local inference model=%s workload=%s op=%s prompt_tokens=%d "
            "generated_tokens=%d tok_per_s=%.1f load_s=%.2f",
            model,
            workload,
            operation,
            prompt_tokens,
            generated_tokens,
            generated_tokens / eval_seconds if eval_seconds > 0 else 0.0,
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

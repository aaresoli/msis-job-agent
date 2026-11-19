"""Benchmark a vLLM model against HOPE's real extraction contract.

Measures time to first token and usage-derived decode throughput through vLLM's
OpenAI-compatible streaming API, then runs the committed gold postings through
the production enrichment graph. It is read-only and never writes checkpoints
or application data.
"""

from __future__ import annotations

import argparse
import json
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import httpx

from hope_job_agent.ai.graphs import STATUS_READY, build_job_enrichment_graph
from hope_job_agent.ai.provider import ModelUnavailable, VllmModelProvider

GOLD_POSTINGS = (
    Path(__file__).resolve().parents[1] / "data" / "gold_job_postings_labeled.json"
)
LATENCY_PROMPT = [
    {
        "role": "user",
        "content": "In two sentences, explain what a business analyst does.",
    }
]


@dataclass
class ModelReport:
    model: str
    first_token_seconds: float | None
    tokens_per_second: float | None
    ready: int
    reviewed: int
    errors: list[str]

    @property
    def compliance_rate(self) -> float:
        total = self.ready + self.reviewed
        return self.ready / total if total else 0.0


def measure_latency(
    base_url: str,
    model: str,
    *,
    reasoning: str,
    max_tokens: int,
    priority: int,
    timeout_seconds: float,
) -> tuple[float | None, float | None]:
    """Return TTFT and usage-derived completion tokens per decode second."""

    body: dict[str, Any] = {
        "model": model,
        "messages": LATENCY_PROMPT,
        "temperature": 0,
        "max_tokens": max_tokens,
        "priority": priority,
        "stream": True,
        "stream_options": {"include_usage": True},
    }
    if reasoning:
        body["reasoning_effort"] = reasoning

    started = time.perf_counter()
    first: float | None = None
    completion_tokens = 0
    try:
        with httpx.stream(
            "POST",
            f"{base_url.rstrip('/')}/v1/chat/completions",
            json=body,
            timeout=httpx.Timeout(timeout_seconds, connect=5),
        ) as response:
            response.raise_for_status()
            for line in response.iter_lines():
                if not line.startswith("data: "):
                    continue
                data = line[6:].strip()
                if data == "[DONE]":
                    continue
                item = json.loads(data)
                usage = item.get("usage") or {}
                completion_tokens = int(
                    usage.get("completion_tokens") or completion_tokens
                )
                choices = item.get("choices") or []
                if choices and (choices[0].get("delta") or {}).get("content"):
                    first = first or time.perf_counter() - started
    except httpx.HTTPError, json.JSONDecodeError:
        return None, None

    elapsed = time.perf_counter() - started
    decode_seconds = elapsed - first if first is not None else 0
    throughput = completion_tokens / decode_seconds if decode_seconds > 0 else None
    return first, throughput


def load_postings() -> list[dict[str, Any]]:
    postings = json.loads(GOLD_POSTINGS.read_text(encoding="utf-8"))
    return [
        {
            "job_id": posting["id"],
            "title": posting["title"],
            "description": posting.get("posting_summary", ""),
        }
        for posting in postings
    ]


def evaluate(
    provider: VllmModelProvider,
    model: str,
    *,
    base_url: str,
    reasoning: str,
    max_tokens: int,
    priority: int,
    timeout_seconds: float,
) -> ModelReport:
    first_token, throughput = measure_latency(
        base_url,
        model,
        reasoning=reasoning,
        max_tokens=max_tokens,
        priority=priority,
        timeout_seconds=timeout_seconds,
    )
    graph = build_job_enrichment_graph(provider)
    ready = 0
    reviewed = 0
    errors: list[str] = []
    for posting in load_postings():
        try:
            result = graph.invoke(dict(posting))
        except ModelUnavailable as exc:
            errors.append(f"{posting['job_id']}: {exc}")
            reviewed += 1
            continue
        if result.get("status") == STATUS_READY:
            ready += 1
        else:
            reviewed += 1
            if result.get("error"):
                errors.append(f"{posting['job_id']}: {result['error'][:160]}")
    return ModelReport(model, first_token, throughput, ready, reviewed, errors)


def format_report(report: ModelReport) -> str:
    first = (
        f"{report.first_token_seconds:.2f}s"
        if report.first_token_seconds is not None
        else "n/a"
    )
    rate = (
        f"{report.tokens_per_second:.1f}"
        if report.tokens_per_second is not None
        else "n/a"
    )
    return (
        f"{report.model:<30} {first:>10} {rate:>10} "
        f"{report.compliance_rate:>10.0%} "
        f"({report.ready}/{report.ready + report.reviewed})"
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "models", nargs="*", default=["openai/gpt-oss-120b"], help="served model IDs"
    )
    parser.add_argument("--base-url", default="http://localhost:8001")
    parser.add_argument("--embedding-base-url", default="http://localhost:8002")
    parser.add_argument("--embedding-model", default="google/embeddinggemma-300m")
    parser.add_argument("--max-model-len", type=int, default=16384)
    parser.add_argument("--max-tokens", type=int, default=2048)
    parser.add_argument("--priority", type=int, default=0)
    parser.add_argument("--reasoning", default="")
    parser.add_argument("--timeout-seconds", type=float, default=300)
    parser.add_argument("--verbose", action="store_true")
    args = parser.parse_args()

    print(f"{'model':<30} {'TTFT':>10} {'tok/s':>10} {'schema ok':>10}")
    print("-" * 68)
    reports: list[ModelReport] = []
    for model in args.models:
        provider = VllmModelProvider(
            args.base_url,
            model,
            args.embedding_model,
            embedding_base_url=args.embedding_base_url,
            timeout_seconds=args.timeout_seconds,
            max_model_len=args.max_model_len,
            max_tokens=args.max_tokens,
            reasoning=args.reasoning,
            priority=args.priority,
            max_parallel=1,
        )
        report = evaluate(
            provider,
            model,
            base_url=args.base_url,
            reasoning=args.reasoning,
            max_tokens=args.max_tokens,
            priority=args.priority,
            timeout_seconds=args.timeout_seconds,
        )
        reports.append(report)
        print(format_report(report))

    if args.verbose:
        for report in reports:
            if report.errors:
                print(f"\n{report.model} rejections:")
                for error in report.errors:
                    print(f"  - {error}")
    return (
        0 if all(report.ready > 0 and report.reviewed == 0 for report in reports) else 1
    )


if __name__ == "__main__":
    raise SystemExit(main())

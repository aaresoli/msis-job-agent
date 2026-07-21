"""Benchmark local Ollama models against this project's real contracts.

Public tok/s benchmarks say nothing about the question that actually decides
the model here: how often does it produce output the enrichment graph will
*accept*? ``ai/graphs.py`` rejects a payload whose evidence quotes are not
present verbatim in the posting, so a fast model that paraphrases is worse than
a slower one that copies. This script measures both, per model:

* first-token latency and sustained tok/s, from a real streaming call
* schema-compliance rate, by running the real ``build_job_enrichment_graph``
  over the committed gold postings and counting how many reach ``ready``
  instead of being routed to ``review``

Usage:

    python scripts/evaluate_local_models.py gpt-oss:120b gpt-oss:20b
    python scripts/evaluate_local_models.py --base-url http://localhost:11434 ...

It only reads. It never writes to the database.
"""

from __future__ import annotations

import argparse
import json
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from hope_job_agent.ai.graphs import STATUS_READY, build_job_enrichment_graph
from hope_job_agent.ai.provider import ModelUnavailable, OllamaModelProvider

GOLD_POSTINGS = (
    Path(__file__).resolve().parents[1] / "data" / "gold_job_postings_labeled.json"
)

LATENCY_PROMPT = [
    {
        "role": "user",
        "content": (
            "In two sentences, explain what a business analyst does. Answer directly."
        ),
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


def measure_latency(provider: OllamaModelProvider) -> tuple[float | None, float | None]:
    """Return (seconds to first chunk, sustained chunks/second).

    Chunks are counted rather than tokens: Ollama emits roughly one chunk per
    token, and counting what actually arrives avoids depending on a tokenizer
    the client does not have.
    """

    started = time.perf_counter()
    first: float | None = None
    chunks = 0
    try:
        for _ in provider.stream_chat(LATENCY_PROMPT):
            if first is None:
                first = time.perf_counter() - started
            chunks += 1
    except ModelUnavailable:
        return None, None
    elapsed = time.perf_counter() - started
    if first is None or elapsed <= first:
        return first, None
    return first, chunks / elapsed


def load_postings() -> list[dict[str, Any]]:
    postings = json.loads(GOLD_POSTINGS.read_text(encoding="utf-8"))
    return [
        {
            "job_id": posting["id"],
            "title": posting["title"],
            # The gold set carries a summary rather than the full posting body.
            # That is the harder case for the quote check, not an easier one:
            # there is less text for a verbatim quote to land in.
            "description": posting.get("posting_summary", ""),
        }
        for posting in postings
    ]


def evaluate(provider: OllamaModelProvider, model: str) -> ModelReport:
    first_token, throughput = measure_latency(provider)
    # No checkpointer: this is a read-only benchmark and should not write
    # LangGraph state into Postgres.
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
        f"{report.model:<24} {first:>10} {rate:>12} "
        f"{report.compliance_rate:>10.0%}  ({report.ready}/"
        f"{report.ready + report.reviewed})"
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("models", nargs="+", help="Ollama model tags to compare")
    parser.add_argument(
        "--base-url",
        default="http://localhost:11434",
        help="Ollama endpoint (default: %(default)s)",
    )
    parser.add_argument(
        "--num-ctx",
        type=int,
        default=32768,
        help="Context window to request (default: %(default)s)",
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Print why each rejected posting was routed to review",
    )
    args = parser.parse_args()

    print(f"{'model':<24} {'1st token':>10} {'chunks/s':>12} {'schema ok':>10}")
    print("-" * 64)
    reports: list[ModelReport] = []
    for model in args.models:
        provider = OllamaModelProvider(
            args.base_url, model, num_ctx=args.num_ctx, keep_alive="2h"
        )
        report = evaluate(provider, model)
        reports.append(report)
        print(format_report(report))

    if args.verbose:
        for report in reports:
            if not report.errors:
                continue
            print(f"\n{report.model} rejections:")
            for error in report.errors:
                print(f"  - {error}")

    print(
        "\n'schema ok' is the share of gold postings the enrichment graph "
        "accepted.\nA low rate with a fast model usually means it paraphrases "
        "evidence quotes\ninstead of copying them verbatim."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

"""CLI + reusable ingest for LinkedIn hiring posts (Apify → ``market_posts``).

Fetches MSIS-relevant LinkedIn *posts* from a completed Apify actor run and
upserts them into the platform ``market_posts`` table, then (unless skipped)
runs the LLM ``market-pulse`` graph to extract cited hiring signals.

Posts, signals, and the market-pulse checkpointer are Postgres/platform
features, so this runner requires a PostgreSQL ``DATABASE_URL``.

Typical usage (feeding a specific completed run's dataset)::

    python -m hope_job_agent.pipeline.run_posts --apify-dataset-id iJpNutUEJl78txYb0
    python -m hope_job_agent.pipeline.run_posts --apify-run-id TUUmhwLxSwnfVtAFJ
"""

from __future__ import annotations

import argparse
import logging
import sys
from collections.abc import Sequence
from typing import Any

from sqlalchemy.orm import Session

from hope_job_agent.db.session import (
    create_db_engine,
    create_session_factory,
    session_scope,
)
from hope_job_agent.persistence.market_post_repository import MarketPostRepository
from hope_job_agent.sources.apify_linkedin_posts import (
    SOURCE_NAME,
    ApifyLinkedInPostsError,
    ApifyLinkedInPostsSource,
)
from hope_job_agent.sources.company_careers.relevance import DEFAULT_RELEVANCE_THRESHOLD
from hope_job_agent.sources.registry import (
    SourceComplianceError,
    ensure_source_allowed,
)

LOGGER = logging.getLogger(__name__)


def ingest_market_posts(
    session: Session,
    *,
    source: ApifyLinkedInPostsSource | None = None,
    dataset_id: str | None = None,
    run_id: str | None = None,
    trigger_run: bool = False,
    max_items: int | None = None,
    relevance_threshold: int = DEFAULT_RELEVANCE_THRESHOLD,
) -> dict[str, Any]:
    """Fetch posts from Apify and upsert them into ``market_posts``.

    Returns a summary dict combining fetch accounting and upsert counts. The
    caller owns the transaction (commit happens on ``session_scope`` exit).
    """

    ensure_source_allowed(SOURCE_NAME)
    source = source or ApifyLinkedInPostsSource(
        dataset_id=dataset_id,
        run_id=run_id,
        trigger_run=trigger_run,
        max_items=max_items,
        relevance_threshold=relevance_threshold,
    )
    result = source.fetch_posts_with_warnings()
    upsert = MarketPostRepository(session).upsert_many(result.posts)
    return {
        "source": SOURCE_NAME,
        "fetch": result.to_summary(),
        "warnings": result.warnings,
        "inserted": upsert.inserted,
        "updated": upsert.updated,
        "unchanged": upsert.unchanged,
    }


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Ingest MSIS-relevant LinkedIn hiring posts from an Apify actor run "
            "into market_posts, then extract hiring signals."
        )
    )
    parser.add_argument(
        "--apify-dataset-id",
        default=None,
        help="Download this exact Apify dataset id (highest priority).",
    )
    parser.add_argument(
        "--apify-run-id",
        default=None,
        help="Resolve the dataset from this Apify actor-run id.",
    )
    parser.add_argument(
        "--apify-trigger-run",
        action="store_true",
        help="Start a fresh (paid) actor run and wait for it to complete.",
    )
    parser.add_argument(
        "--apify-max-items",
        type=int,
        default=None,
        help="Cap the number of dataset items fetched.",
    )
    parser.add_argument(
        "--relevance-threshold",
        type=int,
        default=DEFAULT_RELEVANCE_THRESHOLD,
        help="Minimum MSIS relevance score to keep a post (default: %(default)s).",
    )
    parser.add_argument(
        "--skip-market-pulse",
        action="store_true",
        help="Do not run the LLM market-pulse signal extraction after ingest.",
    )
    parser.add_argument(
        "--database-url",
        default=None,
        help="Override the PostgreSQL DATABASE_URL.",
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Enable debug logging.",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> None:
    """CLI entry point for the LinkedIn posts ingest."""

    parser = _build_parser()
    args = parser.parse_args(argv)
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )

    try:
        factory = create_session_factory(
            create_db_engine(args.database_url, storage="postgres")
        )
    except ValueError as exc:
        print(
            f"Posts ingest requires a PostgreSQL DATABASE_URL: {exc}",
            file=sys.stderr,
        )
        raise SystemExit(1) from exc

    try:
        with session_scope(factory) as session:
            outcome = ingest_market_posts(
                session,
                dataset_id=args.apify_dataset_id,
                run_id=args.apify_run_id,
                trigger_run=args.apify_trigger_run,
                max_items=args.apify_max_items,
                relevance_threshold=args.relevance_threshold,
            )
    except (ApifyLinkedInPostsError, SourceComplianceError) as exc:
        print(f"Posts ingest failed: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc

    fetch = outcome["fetch"]
    print("LinkedIn posts ingest complete")
    print(f"Run: {fetch['run_id']}  Dataset: {fetch['dataset_id']}")
    print(
        f"Fetched: {fetch['raw_count']}  kept: {fetch['kept_count']}  "
        f"skipped_relevance: {fetch['skipped_by_relevance']}  "
        f"skipped_invalid: {fetch['skipped_invalid']}"
    )
    print(
        f"Stored: inserted={outcome['inserted']} updated={outcome['updated']} "
        f"unchanged={outcome['unchanged']}"
    )
    for warning in outcome["warnings"]:
        print(f"Warning: {warning}")

    if args.skip_market_pulse:
        print("Market pulse: skipped (--skip-market-pulse)")
        return

    # Imported lazily so the ingest path does not require Celery/broker config.
    from hope_job_agent.workers.tasks import refresh_market_pulse

    pulse = refresh_market_pulse()
    print(
        f"Market pulse: status={pulse.get('status')} " f"signals={pulse.get('signals')}"
    )


if __name__ == "__main__":
    main()

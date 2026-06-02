"""Command-line entry point for local project checks and pipeline runs."""

import argparse
import sys
from collections.abc import Sequence
from pathlib import Path

from hope_job_agent.config import get_settings
from hope_job_agent.pipeline.runner import run_pipeline
from hope_job_agent.sources.approved_json import (
    ApprovedJsonJobSource,
    ApprovedJsonSourceError,
)


def _print_smoke_status() -> None:
    """Print a lightweight status message for local smoke testing."""

    settings = get_settings()
    print(f"HOPE Job Agent scaffold running in {settings.environment} mode")


def _run_pipeline_command(source_file: Path | None) -> None:
    """Run the approved-source thin-slice pipeline and print a concise summary."""

    settings = get_settings()
    export_path = source_file or settings.sources.approved_jobs_path
    source = ApprovedJsonJobSource(export_path)

    try:
        result = run_pipeline([source])
    except ApprovedJsonSourceError as exc:
        print(f"Pipeline failed: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc

    print("Pipeline run complete")
    print(f"Source file: {export_path}")
    print(f"Raw jobs: {result.raw_count}")
    print(f"Valid jobs: {result.valid_count}")
    print(f"Invalid jobs: {result.invalid_count}")
    print(f"Deduplicated jobs: {result.deduplicated_count}")


def _build_parser() -> argparse.ArgumentParser:
    """Build the CLI argument parser."""

    parser = argparse.ArgumentParser(prog="hope-job-agent")
    subparsers = parser.add_subparsers(dest="command")

    run_parser = subparsers.add_parser(
        "run-pipeline",
        help="Run the approved-source ingestion pipeline against a local JSON export.",
    )
    run_parser.add_argument(
        "--source-file",
        type=Path,
        default=None,
        help="Path to an approved local JSON job export.",
    )

    return parser


def main(argv: Sequence[str] | None = None) -> None:
    """Run the CLI."""

    args = list(sys.argv[1:] if argv is None else argv)
    if not args:
        _print_smoke_status()
        return

    parser = _build_parser()
    namespace = parser.parse_args(args)

    if namespace.command == "run-pipeline":
        _run_pipeline_command(namespace.source_file)
        return

    parser.print_help()
    raise SystemExit(2)


if __name__ == "__main__":
    main()

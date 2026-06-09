"""Command-line entry point for local project checks and pipeline runs."""

import argparse
import sys
from collections.abc import Sequence
from pathlib import Path

from hope_job_agent.config import get_settings
from hope_job_agent.evaluation.evaluate import evaluate_fixture
from hope_job_agent.models.student import StudentProfile
from hope_job_agent.pipeline.runner import run_pipeline
from hope_job_agent.sources.approved_json import (
    ApprovedJsonJobSource,
    ApprovedJsonSourceError,
)
from hope_job_agent.sources.registry import SourceComplianceError


def _print_smoke_status() -> None:
    """Print a lightweight status message for local smoke testing."""

    settings = get_settings()
    print(f"HOPE Job Agent scaffold running in {settings.environment} mode")


def _sample_profiles() -> list[StudentProfile]:
    return [
        StudentProfile(
            name="Sample Data Analytics Student",
            concentration="Data Analytics and AI",
            academic_stage="Incoming student (Fall)",
            target_roles=["Data Analyst / BI Engineer"],
            skills=["SQL", "Python", "Tableau"],
            work_auth_status="Need CPT / OPT sponsorship",
            geo_preference=["Midwest (Chicago, Indy, Cincy)"],
            delivery_preference="Dashboard / spreadsheet view",
        )
    ]


def _run_pipeline_command(source_file: Path | None, output_file: Path | None) -> None:
    """Run the approved-source thin-slice pipeline and print a concise summary."""

    settings = get_settings()
    export_path = source_file or settings.sources.approved_jobs_path
    output_path = output_file or Path("data/output/pipeline_results.json")
    source = ApprovedJsonJobSource(export_path)

    try:
        result = run_pipeline(
            [source],
            student_profiles=_sample_profiles(),
            output_path=output_path,
        )
    except (ApprovedJsonSourceError, SourceComplianceError) as exc:
        print(f"Pipeline failed: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc

    print("Pipeline run complete")
    print(f"Source file: {export_path}")
    print(f"Raw jobs: {result.raw_count}")
    print(f"Valid jobs: {result.valid_count}")
    print(f"Invalid jobs: {result.invalid_count}")
    print(f"Deduplicated jobs: {result.deduplicated_count}")
    print(f"Output file: {result.output_path}")


def _run_evaluation_command(dataset_file: Path | None) -> None:
    dataset_path = dataset_file or Path("tests/fixtures/labelled_postings.json")
    report = evaluate_fixture(dataset_path)
    print("Evaluation complete")
    print(f"Dataset: {dataset_path}")
    print(f"Records: {report.record_count}")
    print(f"Role accuracy: {report.role_accuracy:.2f}")
    print(f"Concentration accuracy: {report.concentration_accuracy:.2f}")
    print(f"Ranking relevance@3: {report.ranking_relevance_at_3:.2f}")


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
    run_parser.add_argument(
        "--output-file",
        type=Path,
        default=None,
        help="Path for the pipeline JSON report.",
    )

    eval_parser = subparsers.add_parser(
        "evaluate",
        help="Evaluate v0 classifier and ranker against the labelled fixture.",
    )
    eval_parser.add_argument(
        "--dataset-file",
        type=Path,
        default=None,
        help="Path to labelled evaluation data.",
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
        _run_pipeline_command(namespace.source_file, namespace.output_file)
        return

    if namespace.command == "evaluate":
        _run_evaluation_command(namespace.dataset_file)
        return

    parser.print_help()
    raise SystemExit(2)


if __name__ == "__main__":
    main()

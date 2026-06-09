"""Evaluate v0 classification and ranking against labelled fixture data."""

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from hope_job_agent.classification.classifier import classify_job
from hope_job_agent.models.job import JobPosting
from hope_job_agent.models.student import StudentProfile
from hope_job_agent.scoring.ranker import rank_jobs_for_student


@dataclass(frozen=True)
class EvaluationReport:
    """Small console-friendly evaluation report."""

    record_count: int
    role_accuracy: float
    concentration_accuracy: float
    ranking_relevance_at_3: float


def evaluate_fixture(dataset_path: Path) -> EvaluationReport:
    """Evaluate classifier and ranker against a labelled JSON fixture."""

    if not dataset_path.exists():
        raise FileNotFoundError(
            f"Labelled evaluation dataset not found: {dataset_path}"
        )

    payload = json.loads(dataset_path.read_text(encoding="utf-8"))
    records = payload.get("postings", [])
    if not records:
        return EvaluationReport(
            record_count=0,
            role_accuracy=0.0,
            concentration_accuracy=0.0,
            ranking_relevance_at_3=0.0,
        )

    jobs = [_job_from_record(record) for record in records]
    role_hits = 0
    concentration_hits = 0

    for record, job in zip(records, jobs, strict=True):
        classification = classify_job(job)
        expected_roles = set(record.get("expected_role_tags", []))
        expected_concentrations = set(record.get("expected_concentration_tags", []))
        if expected_roles.issubset(classification.role_tags):
            role_hits += 1
        if expected_concentrations.issubset(classification.concentration_tags):
            concentration_hits += 1

    ranking_relevance = _ranking_relevance_at_3(
        payload.get("sample_profiles", []), jobs
    )
    return EvaluationReport(
        record_count=len(records),
        role_accuracy=role_hits / len(records),
        concentration_accuracy=concentration_hits / len(records),
        ranking_relevance_at_3=ranking_relevance,
    )


def _job_from_record(record: dict[str, Any]) -> JobPosting:
    return JobPosting(
        source=record["source"],
        title=record["title"],
        company=record["company"],
        location=record["location"],
        description=record["description"],
        url=record["source_url"],
        posted_date=record.get("posted_date"),
        employment_type=record.get("employment_type"),
        seniority=record.get("expected_seniority"),
        opt_cpt_flag=record.get("opt_cpt_flag"),
        raw_metadata={
            "retrieval_date": record.get("retrieval_date"),
            "fixture_id": record.get("id"),
        },
    )


def _ranking_relevance_at_3(
    profile_records: list[dict[str, Any]],
    jobs: list[JobPosting],
) -> float:
    if not profile_records:
        return 0.0

    hits = 0
    for profile_record in profile_records:
        profile = StudentProfile(**profile_record["profile"])
        expected_job_ids = set(profile_record.get("expected_top_job_ids", []))
        ranked = rank_jobs_for_student(profile, jobs)[:3]
        ranked_ids = {
            match.job.raw_metadata.get("fixture_id")
            for match in ranked
            if match.job.raw_metadata.get("fixture_id")
        }
        if ranked_ids & expected_job_ids:
            hits += 1

    return hits / len(profile_records)

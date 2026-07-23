#!/usr/bin/env python3
"""Fetch MSIS LAMP employers including NVIDIA (rank #26)."""

import json
from datetime import UTC, datetime
from pathlib import Path

from hope_job_agent.sources.company_careers import (
    CompanyCareersSource,
    load_company_careers_config,
)
from hope_job_agent.sources.company_careers.http import HttpClient


def fetch_top_ranked(max_ranks=10):
    """Fetch companies up to max_ranks."""
    config = load_company_careers_config()

    # Get enabled companies with student_interest_rank, sorted by rank
    ranked = [
        c for c in config.companies if c.enabled and c.student_interest_rank is not None
    ]
    ranked.sort(key=lambda x: x.student_interest_rank)

    filtered = [c for c in ranked if c.student_interest_rank <= max_ranks]

    print(
        f"Fetching jobs from {len(filtered)} MSIS LAMP employers "
        f"(rank #{max_ranks} and below)..."
    )
    for c in filtered:
        print(f"  #{c.student_interest_rank}: {c.company_name}")

    config.companies = filtered

    client = HttpClient(
        user_agent=(
            "KelleyHOPE-MSIS-JobAgent/0.1 (+https://kelley.iu.edu; fetch script)"
        ),
        min_interval_seconds=1.0,
        timeout_seconds=30.0,
        max_retries=2,
    )

    source = CompanyCareersSource(
        config=config,
        client=client,
    )

    print(f"\nFetching from {len(config.enabled_companies())} companies...")
    result = source.fetch_all_jobs()

    jobs_data = []
    for job in result.jobs:
        jobs_data.append(
            {
                "title": job.title,
                "company": job.company,
                "location": job.location,
                "url": job.url,
                "employment_type": job.employment_type,
                "career_stage": job.career_stage,
                "relevance_score": job.relevance_score,
                "matched_keywords": job.matched_keywords,
                "concentration_tags": job.concentration_tags or [],
            }
        )

    output = {
        "fetched_at": datetime.now(UTC).isoformat(),
        "summary": result.to_summary(),
        "params": {
            "max_rank": max_ranks,
            "companies_count": len(config.enabled_companies()),
        },
        "jobs": jobs_data,
    }

    output_path = Path(f"data/output/msis_lamp_fetch_rank_{max_ranks}.json")
    output_path.parent.mkdir(parents=True, exist_ok=True)

    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(output, f, indent=2, default=str)

    print(f"\n{'=' * 60}")
    print("FETCH SUMMARY")
    print("=" * 60)
    print(f"Companies: {len(result.reports)}")
    print(f"Raw jobs: {result.raw_count}")
    print(f"MSIS-relevant (score >= 3): {result.kept_count}")

    for report in result.reports:
        status = "✓" if report.status == "ok" else f"✗ ({report.status})"
        print(
            f"  {status} {report.company_name}: "
            f"fetched={report.fetched}, kept={report.kept}"
        )

    print(f"\nOutput saved to: {output_path}")


if __name__ == "__main__":
    fetch_top_ranked(50)  # Fetch top 50 by rank

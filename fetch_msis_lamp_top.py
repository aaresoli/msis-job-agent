#!/usr/bin/env python3
"""Fetch MSIS LAMP employers (top ranked by student interest)."""

from pathlib import Path
from datetime import UTC, datetime

from hope_job_agent.sources.company_careers import (
    CompanyCareersSource,
    load_company_careers_config,
)
from hope_job_agent.sources.company_careers.http import HttpClient
import json


def fetch_msis_lamp_companies():
    """Fetch all enabled MSIS LAMP employers."""
    config = load_company_careers_config()
    
    # Get enabled companies with student_interest_rank, sorted by rank
    ranked = [c for c in config.companies 
              if c.enabled and c.student_interest_rank is not None]
    ranked.sort(key=lambda x: x.student_interest_rank)
    
    print(f"Fetching jobs from {len(ranked)} MSIS LAMP employers...")
    print("Top 20 by student interest:")
    for c in ranked[:20]:
        print(f"  #{c.student_interest_rank}: {c.company_name}")
    
    # Keep all enabled ranked companies
    config.companies = ranked
    
    client = HttpClient(
        user_agent="KelleyHOPE-MSIS-JobAgent/0.1 (+https://kelley.iu.edu; fetch script)",
        min_interval_seconds=0.5,  # Moderate rate limiting
        timeout_seconds=30.0,
        max_retries=2,
    )

    source = CompanyCareersSource(
        config=config,
        client=client,
    )

    print(f"\nFetching from {len(config.enabled_companies())} companies...")
    result = source.fetch_all_jobs()

    # Convert to serializable format
    jobs_data = []
    for job in result.jobs:
        jobs_data.append({
            "title": job.title,
            "company": job.company,
            "location": job.location,
            "url": job.url,
            "employment_type": job.employment_type,
            "career_stage": job.career_stage,
            "relevance_score": job.relevance_score,
            "matched_keywords": job.matched_keywords,
            "concentration_tags": job.concentration_tags or [],
        })

    # Add summary
    output = {
        "fetched_at": datetime.now(UTC).isoformat(),
        "summary": result.to_summary(),
        "params": {"msis_lamp_companies": len(config.enabled_companies())},
        "jobs": jobs_data,
    }

    # Save to file
    output_path = Path("data/output/msis_lamp_fetch.json")
    output_path.parent.mkdir(parents=True, exist_ok=True)

    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(output, f, indent=2, default=str)

    print(f"\n{'=' * 60}")
    print("FETCH SUMMARY")
    print("=" * 60)
    print(f"Companies fetched: {len(result.reports)}")
    print(f"Jobs fetched (raw): {result.raw_count}")
    print(f"Jobs kept (MSIS-relevant): {result.kept_count}")

    for report in result.reports:
        status = "✓" if report.status == "ok" else f"✗ ({report.status})"
        print(f"  {status} {report.company_name}: "
              f"fetched={report.fetched}, kept={report.kept}")

    print(f"\nOutput saved to: {output_path}")


if __name__ == "__main__":
    fetch_msis_lamp_companies()

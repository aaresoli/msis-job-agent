#!/usr/bin/env python3
"""Fetch all jobs from company_careers source and save to JSON."""

from pathlib import Path
from datetime import UTC, datetime

from hope_job_agent.sources.company_careers import (
    CompanyCareersSource,
    load_company_careers_config,
)
from hope_job_agent.sources.company_careers.http import HttpClient


def main():
    config = load_company_careers_config()
    
    client = HttpClient(
        user_agent="KelleyHOPE-MSIS-JobAgent/0.1 (+https://kelley.iu.edu; fetch script)",
        min_interval_seconds=1.0,
        timeout_seconds=15.0,
        max_retries=2,
    )
    
    source = CompanyCareersSource(
        config=config,
        client=client,
    )
    
    print(f"Fetching jobs from {len(config.enabled_companies())} enabled companies...")
    print(f"Relevance threshold: {config.relevance_threshold}")
    print("-" * 60)
    
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
        "jobs": jobs_data,
    }
    
    # Save to file
    output_path = Path("data/output/company_careers_fetch.json")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    
    import json
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(output, f, indent=2, default=str)
    
    print(f"\n{'=' * 60}")
    print("FETCH SUMMARY")
    print("=" * 60)
    print(f"Companies fetched: {len(result.reports)}")
    print(f"Jobs fetched (raw): {result.raw_count}")
    print(f"Jobs kept (MSIS-relevant): {result.kept_count}")
    print(f"Duplicates skipped: {result.duplicate_count}")
    
    # Per-company breakdown
    print("\nPer-Company Breakdown:")
    for report in result.reports:
        status = "✓" if report.status == "ok" else f"✗ ({report.status})"
        print(f"  {status} {report.company_name}: "
              f"fetched={report.fetched}, kept={report.kept}, "
              f"skipped_keyword={report.skipped_by_keyword}")

    print(f"\nOutput saved to: {output_path}")


if __name__ == "__main__":
    main()

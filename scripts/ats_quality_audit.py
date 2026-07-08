#!/usr/bin/env python3
"""ATS retained-job quality audit (Markdown + JSON).

Reads the latest ``company_careers`` normalized jobs CSV plus its run summary
and produces:

* Retained-job samples by provider (with company, career stage, and
  concentration tags).
* Flags: senior-heavy companies, zero-kept companies, high fetched / low kept
  ratios, missing MSIS concentration families, and suspiciously generic
  titles worth a manual look.

Usage:

    python scripts/ats_quality_audit.py \
        --jobs outputs/smoke/company_careers_jobs.csv \
        --run-summary outputs/smoke/company_careers_jobs.summary.json \
        [--out outputs/ats_quality_audit.md]

Tune relevance keywords only when this audit shows a concrete issue.
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))

from hope_job_agent.sources.company_careers.reporting import (  # noqa: E402
    build_quality_audit,
    render_quality_markdown,
)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--jobs", required=True, help="Normalized jobs CSV path")
    parser.add_argument("--run-summary", default=None)
    parser.add_argument("--out", default="outputs/ats_quality_audit.md")
    parser.add_argument("--sample-size", type=int, default=6)
    args = parser.parse_args()

    jobs_path = Path(args.jobs)
    if not jobs_path.exists():
        print(f"Jobs CSV not found: {jobs_path}", file=sys.stderr)
        return 1
    with jobs_path.open(encoding="utf-8", newline="") as handle:
        jobs = list(csv.DictReader(handle))

    run_summary = None
    if args.run_summary and Path(args.run_summary).exists():
        run_summary = json.loads(Path(args.run_summary).read_text(encoding="utf-8"))

    audit = build_quality_audit(jobs, run_summary, sample_size=args.sample_size)

    md_path = Path(args.out)
    md_path.parent.mkdir(parents=True, exist_ok=True)
    md_path.write_text(render_quality_markdown(audit), encoding="utf-8")
    json_path = md_path.with_suffix(".json")
    json_path.write_text(json.dumps(audit, indent=2), encoding="utf-8")
    print(f"Wrote {md_path} and {json_path}")
    print(
        json.dumps(
            {
                "total_jobs": audit["total_jobs"],
                "companies": audit["companies"],
                "senior_heavy": len(audit["senior_heavy_companies"]),
                "zero_kept": len(audit["zero_kept_companies"]),
                "low_keep_ratio": len(audit["low_keep_ratio_companies"]),
                "generic_titles": len(audit["suspicious_generic_titles"]),
                "missing_families": audit["missing_concentration_families"],
            },
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

#!/usr/bin/env python3
"""ATS source health report (Markdown + JSON).

Combines three inputs into one operational report (run monthly or before a
demo):

1. ``config/company_careers.yml`` — ranks covered (entries + merged aliases),
   enabled/unsupported/pending counts, and stale ``verified_at`` dates.
2. The latest coverage report (``outputs/company_coverage_report.json``,
   written by ``scripts/research_lamp_companies.py``) — optional.
3. A pipeline run summary (``*.summary.json`` from
   ``hope_job_agent.pipeline.run_mvp``) — optional; contributes live fetch
   outcomes: failed/blocked/robots/empty, zero-kept companies, duplicate
   count, cap warnings, and a per-provider breakdown.

Usage:

    python scripts/ats_health_report.py \
        [--run-summary outputs/smoke/company_careers_jobs.summary.json] \
        [--coverage outputs/company_coverage_report.json] \
        [--stale-days 30] [--out outputs/ats_health_report.md]

The JSON twin is written next to the Markdown (``.md`` -> ``.json``).
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))

from hope_job_agent.sources.company_careers.config import (  # noqa: E402
    load_company_careers_config,
)
from hope_job_agent.sources.company_careers.reporting import (  # noqa: E402
    build_health_stats,
    render_health_markdown,
)


def _load_json(path_str: str | None) -> dict[str, Any] | None:
    if not path_str:
        return None
    path = Path(path_str)
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", default="config/company_careers.yml")
    parser.add_argument("--coverage", default="outputs/company_coverage_report.json")
    parser.add_argument("--run-summary", default=None)
    parser.add_argument("--stale-days", type=int, default=30)
    parser.add_argument("--out", default="outputs/ats_health_report.md")
    args = parser.parse_args()

    config = load_company_careers_config(args.config)
    stats = build_health_stats(
        config,
        coverage_report=_load_json(args.coverage),
        run_summary=_load_json(args.run_summary),
        stale_days=args.stale_days,
    )

    md_path = Path(args.out)
    md_path.parent.mkdir(parents=True, exist_ok=True)
    md_path.write_text(render_health_markdown(stats), encoding="utf-8")
    json_path = md_path.with_suffix(".json")
    json_path.write_text(json.dumps(stats, indent=2, default=str), encoding="utf-8")
    print(f"Wrote {md_path} and {json_path}")

    cfg = stats["config"]
    print(
        json.dumps(
            {
                "ranks_covered_total": cfg["ranks_covered_total"],
                "enabled_ranked": cfg["enabled_ranked"],
                "enabled_total": cfg["enabled_total"],
                "unsupported_ranked": cfg["unsupported_ranked"],
                "pending_ranked": cfg["pending_ranked"],
                "stale_verified": len(cfg["stale_verified"]),
            },
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

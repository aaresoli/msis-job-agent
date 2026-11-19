#!/usr/bin/env python3
"""Low-volume endpoint refresh check for enabled companies (MD + JSON).

Sends exactly ONE small request per enabled company (limit=1 wherever the API
supports it) and flags endpoints that fail, block, or return empty — i.e.
drift from the config's ``verification_status: verified``. It NEVER edits the
config: review ``outputs/ats_refresh_report.md`` and update
``config/company_careers.yml`` (and ``verified_at``) deliberately.

Usage:

    python scripts/ats_refresh_endpoints.py \
        [--config config/company_careers.yml] \
        [--out outputs/ats_refresh_report.md] \
        [--include-pending] [--only NAME] [--min-interval 1.0]
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict
from datetime import UTC, datetime
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))

from hope_job_agent.sources.company_careers.config import (  # noqa: E402
    load_company_careers_config,
)
from hope_job_agent.sources.company_careers.http import HttpClient  # noqa: E402
from hope_job_agent.sources.company_careers.verification import (  # noqa: E402
    verify_target,
)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", default="config/company_careers.yml")
    parser.add_argument("--out", default="outputs/ats_refresh_report.md")
    parser.add_argument(
        "--include-pending",
        action="store_true",
        help="Also probe disabled companies with verification_status: pending",
    )
    parser.add_argument("--only", default=None)
    parser.add_argument("--min-interval", type=float, default=1.0)
    args = parser.parse_args()

    config = load_company_careers_config(args.config)
    targets = [c for c in config.companies if c.enabled]
    if args.include_pending:
        targets += [
            c
            for c in config.companies
            if not c.enabled and c.verification_status == "pending"
        ]
    if args.only:
        needle = args.only.casefold()
        targets = [c for c in targets if needle in c.company_name.casefold()]

    client = HttpClient(min_interval_seconds=args.min_interval)
    now = datetime.now(UTC)
    outcomes = []
    for target in targets:
        outcome = verify_target(client, target)
        outcomes.append(
            {
                **asdict(outcome),
                "config_status": target.verification_status,
                "verified_at": target.verified_at,
                "enabled": target.enabled,
                "drifted": target.enabled and outcome.status != "verified",
            }
        )
        marker = "OK " if outcome.status == "verified" else "!! "
        print(
            f"{marker}{target.company_name:<40} {outcome.status:<10} "
            f"http={outcome.http_status} total={outcome.jobs_total}"
        )

    drifted = [o for o in outcomes if o["drifted"]]
    report = {
        "generated_at": now.isoformat(),
        "probed": len(outcomes),
        "verified": sum(1 for o in outcomes if o["status"] == "verified"),
        "drifted": [o["company"] for o in drifted],
        "outcomes": outcomes,
    }

    md_lines = [
        "# ATS Endpoint Refresh Report",
        "",
        f"Generated: {now.isoformat()}",
        "",
        f"Probed {report['probed']} companies with one low-volume request "
        f"each; {report['verified']} verified.",
        "",
        "This report never mutates config. For drifted companies, re-discover",
        "the endpoint (`scripts/research_lamp_companies.py --live --only NAME`)",
        "and update `config/company_careers.yml` deliberately.",
        "",
        "| Company | Provider | Status | HTTP | Jobs | Config status | Drift |",
        "|---------|----------|--------|------|------|----------------|-------|",
    ]
    for o in outcomes:
        md_lines.append(
            f"| {o['company']} | {o['provider']} | {o['status']} "
            f"| {o['http_status']} | {o['jobs_total']} | {o['config_status']} "
            f"| {'YES' if o['drifted'] else ''} |"
        )
    md_lines.append("")

    md_path = Path(args.out)
    md_path.parent.mkdir(parents=True, exist_ok=True)
    md_path.write_text("\n".join(md_lines), encoding="utf-8")
    json_path = md_path.with_suffix(".json")
    json_path.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(f"\nWrote {md_path} and {json_path}")
    if drifted:
        print(f"DRIFT detected for: {', '.join(o['company'] for o in drifted)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

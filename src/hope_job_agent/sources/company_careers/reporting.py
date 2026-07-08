"""Operational reporting for the company_careers source.

Pure functions consumed by the thin CLIs in ``scripts/``:

* ``build_health_stats`` / ``render_health_markdown`` — config + latest
  coverage report + latest run summary -> one operational health snapshot
  (``scripts/ats_health_report.py``).
* ``build_quality_audit`` / ``render_quality_markdown`` — retained-jobs CSV
  rows + run summary -> sampling and false-positive heuristics
  (``scripts/ats_quality_audit.py``).

Everything here is deterministic and network-free so it is unit-testable.
"""

from __future__ import annotations

import random
import re
from collections import Counter, defaultdict
from datetime import UTC, datetime, timedelta
from typing import Any

from hope_job_agent.classification.taxonomy import MSIS_CONCENTRATIONS
from hope_job_agent.sources.company_careers.config import CompanyCareersConfig
from hope_job_agent.sources.company_careers.relevance import detect_career_stage

FAILED_STATUSES = frozenset({"failed", "blocked", "robots_disallowed"})

# Titles containing none of these tokens are flagged as "suspiciously generic"
# in the quality audit — worth a manual look, not automatically wrong.
_MSIS_TITLE_TOKENS = re.compile(
    r"analy|consult|engineer|data|security|cyber|risk|audit|erp|sap|workday|"
    r"servicenow|salesforce|oracle|cloud|platform|product|system|architect|"
    r"scientist|developer|intelligence|intern|technolog|digital|solution|"
    r"transformation|integration|implementation",
    re.IGNORECASE,
)

_SENIOR_TITLE = re.compile(
    r"\b(senior|sr\.?|principal|director|vp|vice president|head of|chief|"
    r"staff|distinguished)\b",
    re.IGNORECASE,
)


# ---------------------------------------------------------------------------
# Health report
# ---------------------------------------------------------------------------


def build_health_stats(
    config: CompanyCareersConfig,
    *,
    coverage_report: dict[str, Any] | None = None,
    run_summary: dict[str, Any] | None = None,
    stale_days: int = 30,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Combine config, coverage report, and run summary into health stats."""

    now = now or datetime.now(UTC)
    stale_cutoff = now - timedelta(days=stale_days)

    tracked = [c for c in config.companies if c.student_interest_rank is not None]
    enabled = [c for c in config.companies if c.enabled]
    ranks_covered = {c.student_interest_rank for c in tracked}
    merged_alias_ranks = {
        rank: c.company_name for c in tracked for rank in c.merged_excel_ranks
    }
    ranks_covered.update(merged_alias_ranks)

    stale: list[dict[str, str]] = []
    for company in enabled:
        if not company.verified_at:
            stale.append({"company": company.company_name, "verified_at": "never"})
            continue
        try:
            verified = datetime.fromisoformat(company.verified_at).replace(tzinfo=UTC)
        except ValueError:
            stale.append(
                {"company": company.company_name, "verified_at": company.verified_at}
            )
            continue
        if verified < stale_cutoff:
            stale.append(
                {"company": company.company_name, "verified_at": company.verified_at}
            )

    stats: dict[str, Any] = {
        "generated_at": now.isoformat(),
        "stale_days": stale_days,
        "config": {
            "tracked_ranked": len(tracked),
            "ranks_covered_total": len(ranks_covered),
            "merged_alias_ranks": merged_alias_ranks,
            "extras_untracked": len(config.companies) - len(tracked),
            "enabled_total": len(enabled),
            "enabled_ranked": sum(1 for c in tracked if c.enabled),
            "unsupported_ranked": sum(
                1 for c in tracked if c.verification_status == "unsupported"
            ),
            "pending_ranked": sum(
                1 for c in tracked if c.verification_status == "pending"
            ),
            "pending_companies": [
                {"company": c.company_name, "rank": c.student_interest_rank}
                for c in tracked
                if c.verification_status == "pending"
            ],
            "stale_verified": stale,
        },
    }

    if coverage_report:
        stats["coverage"] = coverage_report.get("summary", {})

    if run_summary:
        health = run_summary.get("company_careers_health") or {}
        per_company = health.get("per_company") or []
        warnings = health.get("warnings") or []
        provider_breakdown: dict[str, dict[str, int]] = defaultdict(
            lambda: {"companies": 0, "fetched": 0, "kept": 0}
        )
        for report in per_company:
            entry = provider_breakdown[report.get("provider", "unknown")]
            entry["companies"] += 1
            entry["fetched"] += report.get("fetched", 0)
            entry["kept"] += report.get("kept", 0)
        stats["run"] = {
            "raw_count": health.get("raw_count"),
            "kept_count": health.get("kept_count"),
            "duplicate_count": health.get("duplicate_count"),
            "companies_total": health.get("companies_total"),
            "companies_ok": health.get("companies_ok"),
            "failed": [
                r["company_name"] for r in per_company if r.get("status") == "failed"
            ],
            "blocked": [
                r["company_name"] for r in per_company if r.get("status") == "blocked"
            ],
            "robots_disallowed": [
                r["company_name"]
                for r in per_company
                if r.get("status") == "robots_disallowed"
            ],
            "empty": [
                r["company_name"] for r in per_company if r.get("status") == "empty"
            ],
            "zero_kept": [
                r["company_name"]
                for r in per_company
                if r.get("status") == "ok" and r.get("kept", 0) == 0
            ],
            "cap_hit": any("max_total_jobs_per_run" in w for w in warnings),
            "warnings": warnings,
            "provider_breakdown": dict(provider_breakdown),
        }

    return stats


def render_health_markdown(stats: dict[str, Any]) -> str:
    cfg = stats["config"]
    lines = [
        "# ATS Source Health Report",
        "",
        f"Generated: {stats['generated_at']}  "
        f"(stale threshold: {stats['stale_days']} days)",
        "",
        "## Config coverage",
        "",
        f"- Excel ranks covered: **{cfg['ranks_covered_total']}** "
        f"({cfg['tracked_ranked']} entries + "
        f"{len(cfg['merged_alias_ranks'])} merged aliases: "
        f"{cfg['merged_alias_ranks'] or 'none'})",
        f"- Enabled (ranked / total): **{cfg['enabled_ranked']} / "
        f"{cfg['enabled_total']}**",
        f"- Unsupported with documented reason: **{cfg['unsupported_ranked']}**",
        f"- Pending verification: **{cfg['pending_ranked']}**",
        "",
    ]
    if cfg["pending_companies"]:
        lines.append("### Pending companies")
        lines.append("")
        lines += [
            f"- {p['company']} (rank {p['rank']})" for p in cfg["pending_companies"]
        ]
        lines.append("")
    if cfg["stale_verified"]:
        lines.append("### Enabled companies with stale/missing verification")
        lines.append("")
        lines += [
            f"- {s['company']}: verified_at={s['verified_at']}"
            for s in cfg["stale_verified"]
        ]
        lines.append(
            "\nRe-verify with `python scripts/ats_refresh_endpoints.py` or "
            "`python scripts/research_lamp_companies.py --live`."
        )
        lines.append("")
    else:
        lines.append("All enabled companies verified within the stale window.")
        lines.append("")

    coverage = stats.get("coverage")
    if coverage:
        lines += [
            "## Latest coverage report",
            "",
            f"- Generated: {coverage.get('generated_at')}",
            f"- Companies in Excel top-N: {coverage.get('top_n')}",
            f"- Present in config: {coverage.get('in_config')}",
            f"- Missing from config: {coverage.get('missing_from_config') or 'none'}",
            "",
        ]

    run = stats.get("run")
    if run:
        lines += [
            "## Last ingestion run",
            "",
            f"- Companies fetched: {run['companies_total']} "
            f"(ok: {run['companies_ok']})",
            f"- Raw postings: {run['raw_count']} | kept: {run['kept_count']} | "
            f"duplicates removed: {run['duplicate_count']}",
            f"- Failed: {', '.join(run['failed']) or 'none'}",
            f"- Blocked: {', '.join(run['blocked']) or 'none'}",
            f"- Robots-disallowed: {', '.join(run['robots_disallowed']) or 'none'}",
            f"- Zero results returned: {', '.join(run['empty']) or 'none'}",
            f"- Fetched but zero kept: {', '.join(run['zero_kept']) or 'none'}",
            f"- max_total_jobs_per_run cap hit: "
            f"{'YES - raise the cap' if run['cap_hit'] else 'no'}",
            "",
            "### Provider breakdown",
            "",
            "| Provider | Companies | Fetched | Kept |",
            "|----------|-----------|---------|------|",
        ]
        for provider, entry in sorted(run["provider_breakdown"].items()):
            lines.append(
                f"| {provider} | {entry['companies']} | {entry['fetched']} | "
                f"{entry['kept']} |"
            )
        lines.append("")

    lines += [
        "## Why some employers stay disabled",
        "",
        "`unsupported` and `pending` are intentional compliance outcomes, not",
        "failures: every ranked employer without a compliant public endpoint",
        "stays in `config/company_careers.yml` as `enabled: false` with its",
        "status and reason, so decisions remain auditable. See",
        "`docs/company_careers.md`.",
        "",
    ]
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Quality audit
# ---------------------------------------------------------------------------


def build_quality_audit(
    jobs: list[dict[str, Any]],
    run_summary: dict[str, Any] | None = None,
    *,
    sample_size: int = 6,
    senior_share_threshold: float = 0.5,
    low_keep_ratio: float = 0.05,
    seed: int = 42,
) -> dict[str, Any]:
    """Analyze retained jobs for sampling and likely-quality issues.

    ``jobs`` are rows from the pipeline's normalized jobs CSV (must contain
    ``title``, ``company``, ``source_job_id``, ``concentration_tags``).
    """

    rng = random.Random(seed)
    by_provider: dict[str, list[dict[str, Any]]] = defaultdict(list)
    by_company: dict[str, list[dict[str, Any]]] = defaultdict(list)
    stage_counts: Counter[str] = Counter()
    concentration_counts: Counter[str] = Counter()
    senior_by_company: Counter[str] = Counter()
    generic: list[dict[str, str]] = []

    for job in jobs:
        provider = str(job.get("source_job_id", "")).split(":")[0] or "unknown"
        company = job.get("company") or "unknown"
        title = job.get("title") or ""
        by_provider[provider].append(job)
        by_company[company].append(job)
        stage_counts[detect_career_stage(title)] += 1
        for tag in str(job.get("concentration_tags") or "").split(";"):
            if tag.strip():
                concentration_counts[tag.strip()] += 1
        if _SENIOR_TITLE.search(title):
            senior_by_company[company] += 1
        if not _MSIS_TITLE_TOKENS.search(title):
            generic.append({"company": company, "title": title})

    senior_heavy = [
        {
            "company": company,
            "kept": len(by_company[company]),
            "senior_titled": senior_by_company[company],
            "share": round(senior_by_company[company] / len(by_company[company]), 2),
        }
        for company in by_company
        if len(by_company[company]) >= 5
        and senior_by_company[company] / len(by_company[company])
        >= senior_share_threshold
    ]

    missing_families = sorted(set(MSIS_CONCENTRATIONS) - set(concentration_counts))

    zero_kept: list[str] = []
    low_keep: list[dict[str, Any]] = []
    if run_summary:
        health = run_summary.get("company_careers_health") or {}
        for report in health.get("per_company") or []:
            fetched = report.get("fetched", 0)
            kept = report.get("kept", 0)
            if report.get("status") == "ok" and kept == 0:
                zero_kept.append(report["company_name"])
            elif fetched >= 20 and kept / fetched < low_keep_ratio:
                low_keep.append(
                    {
                        "company": report["company_name"],
                        "fetched": fetched,
                        "kept": kept,
                        "ratio": round(kept / fetched, 3),
                    }
                )

    samples = {
        provider: [
            {
                "company": job.get("company"),
                "title": job.get("title"),
                "career_stage": detect_career_stage(job.get("title") or ""),
                "concentration_tags": job.get("concentration_tags"),
            }
            for job in rng.sample(items, min(sample_size, len(items)))
        ]
        for provider, items in sorted(by_provider.items())
    }

    return {
        "total_jobs": len(jobs),
        "companies": len(by_company),
        "by_provider": {p: len(items) for p, items in sorted(by_provider.items())},
        "career_stages": dict(stage_counts),
        "concentration_counts": dict(concentration_counts),
        "missing_concentration_families": missing_families,
        "senior_heavy_companies": sorted(
            senior_heavy, key=lambda item: -item["share"]
        ),
        "suspicious_generic_titles": generic[:25],
        "zero_kept_companies": zero_kept,
        "low_keep_ratio_companies": low_keep,
        "samples_by_provider": samples,
    }


def render_quality_markdown(audit: dict[str, Any]) -> str:
    lines = [
        "# ATS Quality Audit",
        "",
        f"Retained jobs analyzed: **{audit['total_jobs']}** across "
        f"**{audit['companies']}** companies.",
        "",
        f"- By provider: {audit['by_provider']}",
        f"- Career stages (title-based): {audit['career_stages']}",
        f"- Concentration tags: {audit['concentration_counts']}",
        f"- Missing MSIS families: "
        f"{audit['missing_concentration_families'] or 'none'}",
        "",
        "## Flags",
        "",
    ]
    if audit["senior_heavy_companies"]:
        lines.append("### Senior-heavy companies (>=50% senior-titled keeps)")
        for item in audit["senior_heavy_companies"]:
            lines.append(
                f"- {item['company']}: {item['senior_titled']}/{item['kept']} "
                f"({item['share']:.0%})"
            )
        lines.append("")
    if audit["zero_kept_companies"]:
        lines.append(
            f"### Zero kept: {', '.join(audit['zero_kept_companies'])}"
        )
        lines.append("")
    if audit["low_keep_ratio_companies"]:
        lines.append("### High fetched / low kept (<5%)")
        for item in audit["low_keep_ratio_companies"]:
            lines.append(
                f"- {item['company']}: {item['kept']}/{item['fetched']} "
                f"({item['ratio']:.1%})"
            )
        lines.append("")
    if audit["suspicious_generic_titles"]:
        lines.append("### Suspiciously generic titles (manual check)")
        for item in audit["suspicious_generic_titles"]:
            lines.append(f"- {item['company']}: {item['title']}")
        lines.append("")
    if not any(
        audit[key]
        for key in (
            "senior_heavy_companies",
            "zero_kept_companies",
            "low_keep_ratio_companies",
            "suspicious_generic_titles",
        )
    ):
        lines.append("No quality flags raised.")
        lines.append("")

    lines.append("## Samples by provider")
    lines.append("")
    for provider, samples in audit["samples_by_provider"].items():
        lines.append(f"### {provider}")
        for sample in samples:
            lines.append(
                f"- {sample['company']} | {sample['title']} "
                f"({sample['career_stage']}) [{sample['concentration_tags']}]"
            )
        lines.append("")
    return "\n".join(lines)

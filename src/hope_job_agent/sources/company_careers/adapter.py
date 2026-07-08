"""CompanyCareersSource: orchestrates ATS fetching, filtering, and normalization.

Flow per configured company:

1. Resolve the provider adapter from the ATS provider name.
2. Respect robots.txt for the provider endpoint (where applicable).
3. Fetch raw postings politely (rate limited, retried, timed out).
4. Apply the deterministic MSIS relevance filter (cheap keyword pass).
5. Normalize retained postings into the shared ``JobPosting`` model, preserving
   the provider payload in ``raw_metadata`` for traceability.
6. Record a per-company health report (fetched/kept/skipped/errors).

Global dedup happens both here (intra-source) and again downstream in the
pipeline, so company_careers output plugs into the same flow as KelleyLink/KSBIT.
"""

from __future__ import annotations

import logging
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from pydantic import ValidationError

from hope_job_agent.models.job import JobPosting
from hope_job_agent.pipeline.deduplicate import deduplicate_jobs
from hope_job_agent.sources.base import BaseJobSource
from hope_job_agent.sources.company_careers.config import (
    CompanyCareersConfig,
    CompanyTarget,
    load_company_careers_config,
)
from hope_job_agent.sources.company_careers.http import HttpClient, HttpError
from hope_job_agent.sources.company_careers.providers.base import (
    ProviderError,
    ProviderNotImplementedError,
    RawJob,
)
from hope_job_agent.sources.company_careers.registry import get_provider
from hope_job_agent.sources.company_careers.relevance import (
    RelevanceResult,
    score_relevance,
)
from hope_job_agent.sources.company_careers.robots import RobotsPolicy

LOGGER = logging.getLogger(__name__)

COMPANY_CAREERS_SOURCE_NAME = "company_careers"
_DEFAULT_LOCATION = "Not specified"


@dataclass
class CompanyFetchReport:
    """Health report for one company's fetch."""

    company_name: str
    provider: str
    status: str = "ok"
    fetched: int = 0
    kept: int = 0
    skipped_by_keyword: int = 0
    skipped_by_filter: int = 0
    invalid: int = 0
    error: str | None = None
    last_fetch_at: str | None = None


@dataclass
class CompanyCareersFetchResult:
    """Jobs plus health data for a company_careers run."""

    jobs: list[JobPosting]
    reports: list[CompanyFetchReport]
    raw_count: int
    kept_count: int
    duplicate_count: int
    warnings: list[str] = field(default_factory=list)
    # Ranked LAMP-list coverage snapshot computed from the config; see
    # ``compute_coverage_summary``.
    coverage: dict[str, Any] = field(default_factory=dict)

    def failed_companies(self) -> list[str]:
        """Return names of companies that failed or were blocked."""

        return [
            report.company_name
            for report in self.reports
            if report.status in {"failed", "blocked", "robots_disallowed"}
        ]

    def to_summary(self) -> dict[str, Any]:
        """Return a JSON-serializable health summary for run output."""

        return {
            "raw_count": self.raw_count,
            "kept_count": self.kept_count,
            "duplicate_count": self.duplicate_count,
            "companies_total": len(self.reports),
            "companies_ok": sum(1 for r in self.reports if r.status == "ok"),
            "failed_companies": self.failed_companies(),
            "per_company": [asdict(report) for report in self.reports],
            "warnings": self.warnings,
            "lamp_coverage": self.coverage,
            # Backward-compatible alias for consumers written when only the
            # top 50 were tracked.
            "top50_coverage": self.coverage,
        }


def compute_coverage_summary(
    config: CompanyCareersConfig,
    reports: list[CompanyFetchReport] | None = None,
) -> dict[str, Any]:
    """Summarize ranked LAMP-list coverage from config metadata.

    Tracked companies are those with ``student_interest_rank`` set. Reports,
    when provided, contribute the live smoke outcome for enabled companies.
    """

    tracked = [c for c in config.companies if c.student_interest_rank is not None]
    failed_statuses = {"failed", "blocked", "robots_disallowed"}
    failed_by_name = {
        r.company_name
        for r in (reports or [])
        if r.status in failed_statuses
    }
    # Every Excel rank is covered either by its own entry or as a merged alias
    # of a better-ranked canonical entry.
    ranks_covered = {c.student_interest_rank for c in tracked}
    merged_alias_ranks = {
        rank: c.company_name for c in tracked for rank in c.merged_excel_ranks
    }
    ranks_covered.update(merged_alias_ranks)
    return {
        "tracked_total": len(tracked),
        "ranks_covered_total": len(ranks_covered),
        "merged_alias_ranks": merged_alias_ranks,
        "verified_enabled": sum(
            1 for c in tracked if c.enabled and c.verification_status == "verified"
        ),
        "verified_unsupported": sum(
            1 for c in tracked if c.verification_status == "unsupported"
        ),
        "unverified": sum(
            1 for c in tracked if c.verification_status == "pending"
        ),
        "failed_live_smoke": sorted(
            c.company_name for c in tracked if c.company_name in failed_by_name
        ),
    }


class CompanyCareersSource(BaseJobSource):
    """Fetch MSIS-relevant postings from public employer career pages/ATS APIs."""

    source_name = COMPANY_CAREERS_SOURCE_NAME

    def __init__(
        self,
        *,
        config: CompanyCareersConfig | None = None,
        config_path: str | Path | None = None,
        client: HttpClient | None = None,
        robots: RobotsPolicy | None = None,
    ) -> None:
        if config is None:
            config = load_company_careers_config(config_path)
        self.config = config
        policy = config.fetch_policy
        self.client = client or HttpClient(
            user_agent=policy.user_agent,
            timeout_seconds=policy.timeout_seconds,
            max_retries=policy.max_retries,
            backoff_seconds=policy.backoff_seconds,
            min_interval_seconds=policy.min_interval_seconds,
        )
        self.robots = robots or RobotsPolicy(self.client, enabled=policy.respect_robots)

    def fetch_jobs(self) -> list[JobPosting]:
        """Fetch and return normalized, intra-source-deduped postings."""

        return self.fetch_all_jobs().jobs

    def fetch_all_jobs(self) -> CompanyCareersFetchResult:
        """Fetch every enabled company and return jobs plus health reports."""

        policy = self.config.fetch_policy
        threshold = self.config.relevance_threshold
        reports: list[CompanyFetchReport] = []
        warnings: list[str] = []
        kept_jobs: list[JobPosting] = []
        raw_total = 0

        for target in self.config.enabled_companies():
            if len(kept_jobs) >= policy.max_total_jobs_per_run:
                warnings.append(
                    "Reached max_total_jobs_per_run="
                    f"{policy.max_total_jobs_per_run}; remaining companies skipped."
                )
                break

            report = CompanyFetchReport(
                company_name=target.company_name,
                provider=target.ats_provider,
                last_fetch_at=datetime.now(UTC).isoformat(),
            )
            reports.append(report)

            raw_jobs = self._fetch_company_raw_jobs(target, policy, report, warnings)
            if raw_jobs is None:
                continue

            report.fetched = len(raw_jobs)
            raw_total += len(raw_jobs)
            self._process_company_jobs(
                target=target,
                raw_jobs=raw_jobs,
                threshold=threshold,
                report=report,
                kept_jobs=kept_jobs,
                max_total=policy.max_total_jobs_per_run,
            )

        unique_jobs = deduplicate_jobs(kept_jobs)
        duplicate_count = len(kept_jobs) - len(unique_jobs)
        LOGGER.info(
            "company_careers fetch complete: raw=%s kept=%s unique=%s failed=%s",
            raw_total,
            len(kept_jobs),
            len(unique_jobs),
            sum(1 for r in reports if r.status in {"failed", "blocked"}),
        )

        return CompanyCareersFetchResult(
            jobs=unique_jobs,
            reports=reports,
            raw_count=raw_total,
            kept_count=len(kept_jobs),
            duplicate_count=duplicate_count,
            warnings=warnings,
            coverage=compute_coverage_summary(self.config, reports),
        )

    def health_check(self) -> bool:
        """Return whether at least one enabled company has a usable provider."""

        for target in self.config.enabled_companies():
            if target.provider_is_known and target.ats_provider != "icims":
                return True
        return False

    def _fetch_company_raw_jobs(
        self,
        target: CompanyTarget,
        policy: Any,
        report: CompanyFetchReport,
        warnings: list[str],
    ) -> list[RawJob] | None:
        try:
            provider = get_provider(target.ats_provider)
        except ProviderError as exc:
            report.status = "failed"
            report.error = str(exc)
            warnings.append(f"{target.company_name}: {exc}")
            return None

        try:
            endpoint = provider.primary_endpoint(target)
        except ProviderError as exc:
            report.status = "failed"
            report.error = str(exc)
            warnings.append(f"{target.company_name}: {exc}")
            return None

        if not self.robots.is_allowed(endpoint):
            report.status = "robots_disallowed"
            report.error = f"robots.txt disallows fetching {endpoint}"
            warnings.append(
                f"{target.company_name}: robots.txt disallows {endpoint}; skipped."
            )
            return None

        try:
            raw_jobs = provider.fetch(self.client, target, policy)
        except ProviderNotImplementedError as exc:
            report.status = "not_implemented"
            report.error = str(exc)
            return None
        except HttpError as exc:
            report.status = "blocked" if exc.blocked else "failed"
            report.error = str(exc)
            warnings.append(f"{target.company_name}: fetch failed: {exc}")
            return None
        except ProviderError as exc:
            report.status = "failed"
            report.error = str(exc)
            warnings.append(f"{target.company_name}: fetch failed: {exc}")
            return None

        if not raw_jobs:
            report.status = "empty"
        return raw_jobs

    def _process_company_jobs(
        self,
        *,
        target: CompanyTarget,
        raw_jobs: list[RawJob],
        threshold: int,
        report: CompanyFetchReport,
        kept_jobs: list[JobPosting],
        max_total: int,
    ) -> None:
        for raw in raw_jobs:
            if len(kept_jobs) >= max_total:
                break
            if not self._passes_location_filters(raw, target):
                report.skipped_by_filter += 1
                continue

            relevance = score_relevance(
                raw.title,
                raw.description,
                threshold=threshold,
                keywords_override=target.relevant_keywords_override,
            )
            if not relevance.is_relevant:
                report.skipped_by_keyword += 1
                continue

            job = self._normalize(raw, target, relevance)
            if job is None:
                report.invalid += 1
                continue
            kept_jobs.append(job)
            report.kept += 1

    def _passes_location_filters(self, raw: RawJob, target: CompanyTarget) -> bool:
        location_text = (raw.location or "").casefold()
        if target.location_filters:
            if not any(
                token.casefold() in location_text for token in target.location_filters
            ):
                return False
        if target.country_filters and location_text:
            if not any(
                token.casefold() in location_text for token in target.country_filters
            ):
                return False
        if target.workplace_filters:
            workplace = (raw.location_type or "").casefold()
            if workplace not in {
                token.casefold() for token in target.workplace_filters
            }:
                return False
        return True

    def _normalize(
        self,
        raw: RawJob,
        target: CompanyTarget,
        relevance: RelevanceResult,
    ) -> JobPosting | None:
        url = (raw.url or raw.apply_url or "").strip()
        if not url:
            return None

        description = raw.description.strip()
        if not description:
            description = (
                f"{raw.title} at {raw.company}."
                if raw.title
                else f"Role at {raw.company}."
            )

        slug = (
            raw.raw_payload.get("__slug__")
            if isinstance(raw.raw_payload, dict)
            else None
        )
        provider_slug = target.ats_slug or target.tenant or slug or "board"
        prefixed_source_job_id = (
            f"{target.ats_provider}:{provider_slug}:{raw.source_job_id}"
        )
        fetched_at = datetime.now(UTC)

        raw_metadata = {
            "provider": target.ats_provider,
            "ats_slug": target.ats_slug,
            "tenant": target.tenant,
            "site": target.site,
            "company_priority": target.priority,
            "fetched_at": fetched_at.isoformat(),
            "source_job_id": prefixed_source_job_id,
            "msis_relevance": {
                "score": relevance.score,
                "threshold": self.config.relevance_threshold,
                "matched_keywords": relevance.matched_keywords,
                "concentration_hints": relevance.concentration_hints,
                "career_stage": relevance.career_stage,
                "reasons": relevance.reasons,
            },
            "provider_payload": raw.raw_payload,
        }

        try:
            return JobPosting(
                source=self.source_name,
                source_job_id=prefixed_source_job_id,
                title=raw.title,
                company=raw.company,
                location=raw.location or _DEFAULT_LOCATION,
                description=description,
                url=url,
                posted_date=raw.posted_date,
                employment_type=raw.employment_type,
                source_detail=f"{target.ats_provider}:{provider_slug}",
                apply_url=raw.apply_url or url,
                location_type=raw.location_type,
                department=raw.department,
                compensation=raw.compensation,
                career_stage=relevance.career_stage,
                relevance_score=float(relevance.score),
                matched_keywords=relevance.matched_keywords,
                raw_metadata=raw_metadata,
                retrieved_at=fetched_at,
            )
        except ValidationError as exc:
            LOGGER.warning(
                "company_careers skipped invalid posting from %s: %s",
                target.company_name,
                exc,
            )
            return None

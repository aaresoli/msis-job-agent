"""Pure filtering, faceting, and presentation logic for the dashboard API.

Everything here operates on in-memory ``(job_key, JobPosting)`` pairs so it is
unit-testable without HTTP or SQLite.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta

from hope_job_agent.classification.career_track import (
    CAREER_TRACK_INTERNSHIP,
    infer_career_track,
)
from hope_job_agent.classification.taxonomy import (
    CONCENTRATION_CODES,
    MSIS_CONCENTRATIONS,
)
from hope_job_agent.models.job import JobPosting
from hope_job_agent.utils.us_location import is_us_location

from .schemas import (
    FacetCount,
    JobCard,
    JobDetail,
    JobsFacets,
    LatestRun,
    StatsResponse,
)

Entry = tuple[str, JobPosting]

TRACK_INTERNSHIP = "internship"
TRACK_FULL_TIME = "full_time"

# Postings older than this never show up in the dashboard. Postings with no
# parseable posted_date are kept (we can't tell their age).
MAX_POSTING_AGE_DAYS = 30

_SOURCE_BADGES = {
    "greenhouse": "Greenhouse",
    "lever": "Lever",
    "ashby": "Ashby",
    "smartrecruiters": "SmartRecruiters",
    "workday": "Workday",
    "oraclecloud": "Oracle Cloud",
    "icims": "iCIMS",
    "apify": "LinkedIn",
}

_SOURCE_NAME_BADGES = {
    "apify_linkedin": "LinkedIn",
    "ksbit_export": "KelleyLink",
    "kelleylink_excel": "KelleyLink",
    "approved_json": "Curated",
    "employer_careers": "Employer Careers",
}

# Providers whose CSS slug differs from the provider key itself.
_PROVIDER_SLUGS = {"apify": "linkedin"}

_SOURCE_NAME_SLUGS = {
    "apify_linkedin": "linkedin",
    "ksbit_export": "kelleylink",
    "kelleylink_excel": "kelleylink",
    "approved_json": "curated",
    "employer_careers": "employer",
}


@dataclass(frozen=True)
class JobQuery:
    """Normalized filter parameters shared by /api/jobs and /matches."""

    track: str | None = None
    concentrations: list[str] = field(default_factory=list)
    roles: list[str] = field(default_factory=list)
    sources: list[str] = field(default_factory=list)
    q: str | None = None
    location: str | None = None
    remote_only: bool = False
    sponsorship_only: bool = False


def effective_track(job: JobPosting) -> str:
    """Return the binary dashboard track for a posting.

    ``unknown`` postings surface on the full-time tab so nothing disappears
    from both tabs; rows persisted before the career_track field existed are
    inferred on the fly.
    """

    track = job.career_track or infer_career_track(job)
    if track == CAREER_TRACK_INTERNSHIP:
        return TRACK_INTERNSHIP
    return TRACK_FULL_TIME


def source_badge(job: JobPosting) -> str:
    """Human-readable source label (LinkedIn, Greenhouse, Workday, ...)."""

    provider = _source_provider(job)
    if provider and provider in _SOURCE_BADGES:
        return _SOURCE_BADGES[provider]
    return _SOURCE_NAME_BADGES.get(job.source, job.source)


def source_slug(job: JobPosting) -> str:
    """Stable lowercase identifier for per-source styling (CSS classes)."""

    provider = _source_provider(job)
    if provider:
        return _PROVIDER_SLUGS.get(provider, provider)
    return _SOURCE_NAME_SLUGS.get(job.source, "other")


def source_attribution(job: JobPosting) -> str:
    """Full provenance sentence shown on cards (tooltip) and in the drawer."""

    provider = _source_provider(job)
    if provider == "apify":
        return "Fetched from LinkedIn via the Apify job scraper"
    if provider and provider in _SOURCE_BADGES:
        return (
            f"Fetched from {job.company}'s careers site "
            f"({_SOURCE_BADGES[provider]} ATS)"
        )
    if job.source in {"ksbit_export", "kelleylink_excel"}:
        return "Fetched from a KelleyLink (12Twenty) export"
    if job.source == "approved_json":
        return "Curated listing approved by the HOPE team"
    return f"Fetched from {source_badge(job)}"


def _source_provider(job: JobPosting) -> str | None:
    detail = (job.source_detail or "").strip()
    if not detail:
        return None
    return detail.split(":", 1)[0].casefold()


def apply_filters(entries: list[Entry], query: JobQuery) -> list[Entry]:
    """Filter entries by every populated field of the query."""

    selected_concentrations = {value.casefold() for value in query.concentrations}
    selected_roles = {value.casefold() for value in query.roles}
    selected_sources = {value.casefold() for value in query.sources}
    text_query = (query.q or "").casefold().strip()
    location_query = (query.location or "").casefold().strip()

    max_age_cutoff = (datetime.now(UTC) - timedelta(days=MAX_POSTING_AGE_DAYS)).date()

    results: list[Entry] = []
    for job_key, job in entries:
        if job.posted_date is not None and job.posted_date < max_age_cutoff:
            continue
        if not is_us_location(job.location):
            continue
        if query.track in {TRACK_INTERNSHIP, TRACK_FULL_TIME} and (
            effective_track(job) != query.track
        ):
            continue
        if selected_concentrations and not (
            selected_concentrations & {tag.casefold() for tag in job.concentration_tags}
        ):
            continue
        if selected_roles and not (
            selected_roles & {tag.casefold() for tag in job.role_tags}
        ):
            continue
        if selected_sources and source_badge(job).casefold() not in selected_sources:
            continue
        if text_query and not _matches_text(job, text_query):
            continue
        if location_query and location_query not in job.location.casefold():
            continue
        if query.remote_only and not _is_remote(job):
            continue
        if query.sponsorship_only and job.opt_cpt_flag is not True:
            continue
        results.append((job_key, job))
    return results


def sort_entries(entries: list[Entry], sort: str | None) -> list[Entry]:
    """Sort filtered entries: recent (default), relevance, or company."""

    if sort == "company":
        return sorted(
            entries,
            key=lambda entry: (entry[1].company.casefold(), entry[1].title.casefold()),
        )
    if sort == "relevance":
        return sorted(
            entries,
            key=lambda entry: (
                -(entry[1].relevance_score or 0.0),
                _date_sort_value(entry[1]),
                entry[1].company.casefold(),
            ),
        )
    return sorted(
        entries,
        key=lambda entry: (
            _date_sort_value(entry[1]),
            -(entry[1].relevance_score or 0.0),
            entry[1].company.casefold(),
        ),
    )


def compute_facets(entries: list[Entry]) -> JobsFacets:
    """Facet counts for the sidebar, computed over the given entry set."""

    concentration_counts: Counter[str] = Counter()
    source_counts: Counter[str] = Counter()
    role_counts: Counter[str] = Counter()
    track_counts: Counter[str] = Counter()
    for _job_key, job in entries:
        track_counts[effective_track(job)] += 1
        source_counts[source_badge(job)] += 1
        for tag in job.concentration_tags:
            concentration_counts[tag] += 1
        for tag in job.role_tags:
            role_counts[tag] += 1

    return JobsFacets(
        concentrations=[
            FacetCount(
                name=name,
                code=CONCENTRATION_CODES.get(name),
                count=concentration_counts.get(name, 0),
            )
            for name in MSIS_CONCENTRATIONS
        ],
        sources=[
            FacetCount(name=name, count=count)
            for name, count in sorted(
                source_counts.items(), key=lambda item: (-item[1], item[0])
            )
        ],
        roles=[
            FacetCount(name=name, count=count)
            for name, count in sorted(
                role_counts.items(), key=lambda item: (-item[1], item[0])
            )
        ],
        tracks={
            TRACK_INTERNSHIP: track_counts.get(TRACK_INTERNSHIP, 0),
            TRACK_FULL_TIME: track_counts.get(TRACK_FULL_TIME, 0),
        },
    )


def compute_stats(
    entries: list[Entry],
    latest_run: dict[str, object] | None,
    *,
    db_exists: bool,
) -> StatsResponse:
    """Program-wide stats for the dashboard header strip."""

    facets = compute_facets(entries)
    week_ago = (datetime.now(UTC) - timedelta(days=7)).date()
    new_this_week = sum(
        1
        for _job_key, job in entries
        if job.posted_date is not None and job.posted_date >= week_ago
    )
    sponsorship_count = sum(1 for _job_key, job in entries if job.opt_cpt_flag is True)
    company_count = len({job.company.casefold() for _job_key, job in entries})

    return StatsResponse(
        db_exists=db_exists,
        total_jobs=len(entries),
        internship_count=facets.tracks[TRACK_INTERNSHIP],
        full_time_count=facets.tracks[TRACK_FULL_TIME],
        sponsorship_count=sponsorship_count,
        new_this_week=new_this_week,
        company_count=company_count,
        by_source=facets.sources,
        by_concentration=facets.concentrations,
        latest_run=(
            LatestRun.model_validate(latest_run) if latest_run is not None else None
        ),
    )


def job_card(job_key: str, job: JobPosting) -> JobCard:
    """Project a posting into the card shape the grid renders."""

    return JobCard(
        job_key=job_key,
        title=job.title,
        company=job.company,
        location=job.location,
        location_type=job.location_type,
        source=job.source,
        source_badge=source_badge(job),
        source_slug=source_slug(job),
        source_attribution=source_attribution(job),
        company_logo=_metadata_str(job, "company_logo"),
        company_url=_metadata_str(job, "company_url"),
        career_track=effective_track(job),
        employment_type=job.employment_type,
        seniority=job.seniority,
        department=job.department,
        compensation=job.compensation,
        posted_date=job.posted_date,
        concentration_tags=job.concentration_tags,
        concentration_codes=[
            CONCENTRATION_CODES.get(tag, tag) for tag in job.concentration_tags
        ],
        role_tags=job.role_tags,
        opt_cpt_flag=job.opt_cpt_flag,
        relevance_score=job.relevance_score,
        apply_url=job.apply_url or job.url,
        url=job.url,
    )


def job_detail(job_key: str, job: JobPosting) -> JobDetail:
    """Project a posting into the drawer shape, including the description."""

    card = job_card(job_key, job)
    return JobDetail(
        **card.model_dump(),
        description=job.description,
        sector=_metadata_str(job, "sector"),
        work_type=_metadata_str(job, "work_type"),
        applications_count=_metadata_str(job, "applications_count"),
        matched_keywords=job.matched_keywords,
        classification_uncertain=job.classification_uncertain,
        retrieved_at=job.retrieved_at.isoformat() if job.retrieved_at else None,
    )


def _matches_text(job: JobPosting, text_query: str) -> bool:
    haystack = " ".join(
        [job.title, job.company, job.location, job.description]
    ).casefold()
    return text_query in haystack


def _is_remote(job: JobPosting) -> bool:
    location_type = (job.location_type or "").casefold()
    return "remote" in location_type or "remote" in job.location.casefold()


def _date_sort_value(job: JobPosting) -> int:
    if job.posted_date is None:
        return 0
    return -job.posted_date.toordinal()


def _metadata_str(job: JobPosting, key: str) -> str | None:
    value = (job.raw_metadata or {}).get(key)
    text = str(value or "").strip()
    return text or None

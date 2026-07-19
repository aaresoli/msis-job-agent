"""Response models for the demo dashboard API."""

from __future__ import annotations

from datetime import date
from typing import Any

from pydantic import BaseModel, Field


class JobCard(BaseModel):
    """Compact posting shape rendered as a card in the dashboard grid."""

    job_key: str
    title: str
    company: str
    location: str
    location_type: str | None = None
    source: str
    source_badge: str
    company_logo: str | None = None
    company_url: str | None = None
    career_track: str
    employment_type: str | None = None
    seniority: str | None = None
    department: str | None = None
    compensation: str | None = None
    posted_date: date | None = None
    concentration_tags: list[str] = Field(default_factory=list)
    concentration_codes: list[str] = Field(default_factory=list)
    role_tags: list[str] = Field(default_factory=list)
    opt_cpt_flag: bool | None = None
    relevance_score: float | None = None
    apply_url: str | None = None
    url: str


class JobDetail(JobCard):
    """Full posting shape rendered in the detail drawer."""

    description: str
    sector: str | None = None
    work_type: str | None = None
    applications_count: str | None = None
    matched_keywords: list[str] = Field(default_factory=list)
    classification_uncertain: bool = False
    retrieved_at: str | None = None


class FacetCount(BaseModel):
    name: str
    code: str | None = None
    count: int


class JobsFacets(BaseModel):
    concentrations: list[FacetCount] = Field(default_factory=list)
    sources: list[FacetCount] = Field(default_factory=list)
    roles: list[FacetCount] = Field(default_factory=list)
    tracks: dict[str, int] = Field(default_factory=dict)


class JobsResponse(BaseModel):
    total: int
    offset: int
    limit: int
    jobs: list[JobCard]
    facets: JobsFacets


class LatestRun(BaseModel):
    run_id: str
    source: str
    completed_at: str
    unique_count: int
    runtime_seconds: float | None = None


class StatsResponse(BaseModel):
    db_exists: bool
    total_jobs: int
    internship_count: int
    full_time_count: int
    sponsorship_count: int
    new_this_week: int
    company_count: int
    by_source: list[FacetCount]
    by_concentration: list[FacetCount]
    latest_run: LatestRun | None = None


class ProfileSummary(BaseModel):
    student_id: str
    name: str
    concentration: str
    academic_stage: str | None = None
    target_roles: list[str] = Field(default_factory=list)
    skills: list[str] = Field(default_factory=list)
    work_auth_status: str | None = None
    needs_cpt_opt: bool = False
    geo_preference: list[str] = Field(default_factory=list)
    remote_preference: str | None = None


class RankedJob(BaseModel):
    job: JobCard
    score: float
    reasons: list[str] = Field(default_factory=list)
    score_breakdown: dict[str, Any] = Field(default_factory=dict)


class MatchesResponse(BaseModel):
    profile: ProfileSummary
    total: int
    matches: list[RankedJob]


class TaxonomyEntry(BaseModel):
    name: str
    code: str


class TaxonomyResponse(BaseModel):
    concentrations: list[TaxonomyEntry]
    roles: list[str]
    tracks: list[str]


class HealthResponse(BaseModel):
    status: str
    db_path: str
    db_exists: bool
    job_count: int
    latest_run_at: str | None = None

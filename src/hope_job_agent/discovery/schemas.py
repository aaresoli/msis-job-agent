"""Response models for the discovery API."""

from __future__ import annotations

from datetime import date

from pydantic import BaseModel, Field


class JobCard(BaseModel):
    """Compact posting shape rendered as a card in the jobs grid."""

    job_key: str
    title: str
    company: str
    location: str
    location_type: str | None = None
    source: str
    source_badge: str
    source_slug: str = "other"
    source_attribution: str = ""
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


class TaxonomyEntry(BaseModel):
    name: str
    code: str


class TaxonomyResponse(BaseModel):
    concentrations: list[TaxonomyEntry]
    roles: list[str]
    tracks: list[str]


# --- LinkedIn hiring posts -------------------------------------------------


class PostSignal(BaseModel):
    """LLM-extracted hiring signal that cites a post (market-pulse)."""

    topic: str
    summary: str
    company_name: str | None = None
    role_tags: list[str] = Field(default_factory=list)
    confidence: float | None = None


class PostCard(BaseModel):
    """Compact hiring-post shape rendered as a card in the Posts grid."""

    post_key: str
    author_name: str | None = None
    company_name: str | None = None
    content_excerpt: str
    source_url: str
    published_at: str | None = None
    relevance_score: float | None = None
    concentration_tags: list[str] = Field(default_factory=list)
    concentration_codes: list[str] = Field(default_factory=list)
    matched_keywords: list[str] = Field(default_factory=list)
    has_signal: bool = False
    signal_summary: str | None = None


class PostDetail(PostCard):
    """Full hiring-post shape rendered in the detail drawer."""

    content: str
    career_stage: str | None = None
    signals: list[PostSignal] = Field(default_factory=list)


class PostsFacets(BaseModel):
    concentrations: list[FacetCount] = Field(default_factory=list)
    companies: list[FacetCount] = Field(default_factory=list)


class PostsResponse(BaseModel):
    total: int
    offset: int
    limit: int
    posts: list[PostCard]
    facets: PostsFacets


class PostStatsResponse(BaseModel):
    db_exists: bool
    total_posts: int
    company_count: int
    new_this_week: int
    with_opportunity: int
    by_concentration: list[FacetCount] = Field(default_factory=list)
    latest_post_at: str | None = None

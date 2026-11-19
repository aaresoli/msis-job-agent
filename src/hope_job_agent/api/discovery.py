"""Faceted job and hiring-post discovery.

These routes carry capabilities the flat ``/jobs`` search cannot express:
sidebar facet counts, internship vs full-time binning, source provenance
labelling, and the freshness and US-location floors applied to every view.

They read whole :class:`~hope_job_agent.models.job.JobPosting` payloads out of
``job_postings.job_json`` and filter them in memory. That is deliberate: the
faceting has to count across the *unfiltered* set to keep sidebar counts
meaningful while individual facets are toggled, which is a poor fit for SQL and
a natural one for the pure functions in :mod:`hope_job_agent.discovery.service`.
The snapshot behind it is TTL-cached, so a page load is one query at most.
"""

from __future__ import annotations

from functools import lru_cache
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query

from hope_job_agent.api.dependencies import current_user
from hope_job_agent.classification.career_track import CAREER_TRACKS
from hope_job_agent.classification.taxonomy import (
    CONCENTRATION_CODES,
    MSIS_CONCENTRATIONS,
    MSIS_TARGET_ROLES,
)
from hope_job_agent.db.platform_models import User
from hope_job_agent.discovery.posts_service import (
    PostQuery,
    apply_post_filters,
    compute_post_facets,
    compute_post_stats,
    post_card,
    post_detail,
    sort_posts,
)
from hope_job_agent.discovery.repository import (
    PostgresJobRepository,
    PostgresPostRepository,
)
from hope_job_agent.discovery.schemas import (
    JobDetail,
    JobsResponse,
    PostDetail,
    PostsResponse,
    PostStatsResponse,
    StatsResponse,
    TaxonomyEntry,
    TaxonomyResponse,
)
from hope_job_agent.discovery.service import (
    JobQuery,
    apply_filters,
    compute_facets,
    compute_stats,
    job_card,
    job_detail,
    sort_entries,
)

router = APIRouter(prefix="/discovery", tags=["discovery"])


@lru_cache(maxsize=1)
def _jobs() -> PostgresJobRepository:
    """One repository per process; each builds its own engine and cache."""

    return PostgresJobRepository()


@lru_cache(maxsize=1)
def _posts() -> PostgresPostRepository:
    return PostgresPostRepository()


@router.get("/jobs", response_model=JobsResponse)
def list_jobs(
    track: str | None = None,
    concentration: Annotated[list[str] | None, Query()] = None,
    role: Annotated[list[str] | None, Query()] = None,
    source: Annotated[list[str] | None, Query()] = None,
    q: str | None = None,
    location: str | None = None,
    remote: bool = False,
    sponsorship: bool = False,
    sort: str | None = None,
    limit: Annotated[int, Query(ge=1, le=500)] = 60,
    offset: Annotated[int, Query(ge=0)] = 0,
    user: User = Depends(current_user),
) -> JobsResponse:
    del user
    snapshot = _jobs().load()
    query = JobQuery(
        track=track,
        concentrations=concentration or [],
        roles=role or [],
        sources=source or [],
        q=q,
        location=location,
        remote_only=remote,
        sponsorship_only=sponsorship,
    )
    filtered = apply_filters(snapshot.entries, query)
    # Facets reflect the current track and search but ignore the facet
    # selections themselves, so the sidebar counts stay meaningful while
    # individual groups are being toggled.
    facet_entries = apply_filters(
        snapshot.entries, JobQuery(track=query.track, q=query.q)
    )
    ordered = sort_entries(filtered, sort)
    page = ordered[offset : offset + limit]
    return JobsResponse(
        total=len(ordered),
        offset=offset,
        limit=limit,
        jobs=[job_card(job_key, job) for job_key, job in page],
        facets=compute_facets(facet_entries),
    )


@router.get("/jobs/{job_key}", response_model=JobDetail)
def get_job(job_key: str, user: User = Depends(current_user)) -> JobDetail:
    del user
    for key, job in _jobs().load().entries:
        if key == job_key:
            return job_detail(key, job)
    raise HTTPException(status_code=404, detail=f"Unknown job: {job_key}")


@router.get("/stats", response_model=StatsResponse)
def stats(user: User = Depends(current_user)) -> StatsResponse:
    del user
    snapshot = _jobs().load()
    return compute_stats(
        snapshot.entries, snapshot.latest_run, db_exists=snapshot.db_exists
    )


@router.get("/posts", response_model=PostsResponse)
def list_posts(
    concentration: Annotated[list[str] | None, Query()] = None,
    company: str | None = None,
    q: str | None = None,
    sort: str | None = None,
    limit: Annotated[int, Query(ge=1, le=500)] = 60,
    offset: Annotated[int, Query(ge=0)] = 0,
    user: User = Depends(current_user),
) -> PostsResponse:
    del user
    snapshot = _posts().load()
    query = PostQuery(concentrations=concentration or [], company=company, q=q)
    filtered = apply_post_filters(snapshot.posts, query)
    facet_posts = apply_post_filters(snapshot.posts, PostQuery(q=query.q))
    ordered = sort_posts(filtered, sort)
    page = ordered[offset : offset + limit]
    return PostsResponse(
        total=len(ordered),
        offset=offset,
        limit=limit,
        posts=[post_card(post) for post in page],
        facets=compute_post_facets(facet_posts),
    )


@router.get("/posts/stats", response_model=PostStatsResponse)
def post_stats(user: User = Depends(current_user)) -> PostStatsResponse:
    del user
    snapshot = _posts().load()
    return compute_post_stats(
        snapshot.posts,
        db_exists=snapshot.db_exists,
        latest_post_at=snapshot.latest_post_at,
    )


@router.get("/posts/{post_key}", response_model=PostDetail)
def get_post(post_key: str, user: User = Depends(current_user)) -> PostDetail:
    del user
    for post in _posts().load().posts:
        if post.post_key == post_key:
            return post_detail(post)
    raise HTTPException(status_code=404, detail=f"Unknown post: {post_key}")


@router.get("/taxonomy", response_model=TaxonomyResponse)
def taxonomy(user: User = Depends(current_user)) -> TaxonomyResponse:
    """Concentrations, roles, and tracks, so clients stop hard-coding them."""

    del user
    return TaxonomyResponse(
        concentrations=[
            TaxonomyEntry(name=name, code=CONCENTRATION_CODES.get(name, name))
            for name in MSIS_CONCENTRATIONS
        ],
        roles=list(MSIS_TARGET_ROLES),
        tracks=list(CAREER_TRACKS),
    )

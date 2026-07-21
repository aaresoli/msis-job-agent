"""FastAPI application for the MSIS student demo dashboard.

Run locally with:

    python -m uvicorn hope_job_agent.dashboard.app:app --port 8010

The app is read-only: it serves the SQLite store populated by
``python -m hope_job_agent.pipeline.run_mvp`` plus the sample student
profiles, with a self-contained static UI at ``/``.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Annotated

from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy.exc import SQLAlchemyError

from hope_job_agent.classification.career_track import CAREER_TRACKS
from hope_job_agent.classification.taxonomy import (
    CONCENTRATION_CODES,
    MSIS_CONCENTRATIONS,
    MSIS_TARGET_ROLES,
)
from hope_job_agent.config import get_settings
from hope_job_agent.config.database import resolve_database_url
from hope_job_agent.scoring.ranker import (
    DEFAULT_RANKING_WEIGHTS,
    RankingWeightsConfigError,
    load_ranking_weights,
    rank_jobs_for_student,
)
from hope_job_agent.storage.sqlite_store import (
    DEFAULT_DATABASE_PATH,
    SQLiteJobStoreError,
    resolve_sqlite_database,
)

from .db import (
    JobRepository,
    NullPostRepository,
    PostgresJobRepository,
    PostgresPostRepository,
)
from .posts_service import (
    PostQuery,
    apply_post_filters,
    compute_post_facets,
    compute_post_stats,
    post_card,
    post_detail,
    sort_posts,
)
from .profiles import load_profiles
from .schemas import (
    HealthResponse,
    JobDetail,
    JobsResponse,
    MatchesResponse,
    PostDetail,
    PostsResponse,
    PostStatsResponse,
    ProfileSummary,
    RankedJob,
    StatsResponse,
    TaxonomyEntry,
    TaxonomyResponse,
)
from .service import (
    JobQuery,
    apply_filters,
    compute_facets,
    compute_stats,
    job_card,
    job_detail,
    sort_entries,
)

STATIC_DIR = Path(__file__).parent / "static"

APP_VERSION = "0.1.0"

LOGGER = logging.getLogger(__name__)


def _default_db_path() -> Path:
    try:
        database = resolve_sqlite_database(
            get_settings().database_url.get_secret_value()
        )
    except SQLiteJobStoreError:
        return DEFAULT_DATABASE_PATH
    return database.path or DEFAULT_DATABASE_PATH


def _profile_summary(student_id: str, profile) -> ProfileSummary:  # noqa: ANN001
    return ProfileSummary(
        student_id=student_id,
        name=profile.name,
        concentration=profile.concentration,
        academic_stage=profile.academic_stage,
        target_roles=profile.target_roles,
        skills=profile.skills,
        work_auth_status=profile.work_auth_status,
        needs_cpt_opt=profile.needs_cpt_opt,
        geo_preference=profile.geo_preference,
        remote_preference=profile.remote_preference,
    )


def _default_repository() -> JobRepository | PostgresJobRepository:
    """Read Postgres when DATABASE_URL points at it, else the SQLite store."""

    url = resolve_database_url(None, storage="auto")
    if url.casefold().startswith("postgres"):
        try:
            return PostgresJobRepository(url)
        except (SQLAlchemyError, ValueError):
            LOGGER.exception(
                "Dashboard could not open the Postgres store; "
                "falling back to the local SQLite store"
            )
    return JobRepository(_default_db_path())


def _default_post_repository() -> PostgresPostRepository | NullPostRepository:
    """Read Postgres ``market_posts`` when available, else serve no posts.

    Posts and their LLM signals live only in the platform Postgres DB, so the
    SQLite demo returns an empty snapshot (graceful empty Posts tab).
    """

    url = resolve_database_url(None, storage="auto")
    if url.casefold().startswith("postgres"):
        try:
            return PostgresPostRepository(url)
        except (SQLAlchemyError, ValueError):
            LOGGER.exception(
                "Dashboard could not open the Postgres posts store; "
                "the Posts tab will be empty"
            )
    return NullPostRepository()


def create_app(
    db_path: Path | None = None,
    profiles_path: Path | None = None,
) -> FastAPI:
    """Build the dashboard app around one job store and profile file.

    An explicit ``db_path`` always selects the SQLite store so the offline demo
    can be pointed at a fixture database.
    """

    repository = JobRepository(db_path) if db_path else _default_repository()
    # An explicit SQLite fixture path has no posts store; serve none.
    post_repository = NullPostRepository() if db_path else _default_post_repository()
    profiles = load_profiles(profiles_path)
    try:
        ranking_weights = load_ranking_weights()
    except RankingWeightsConfigError:
        ranking_weights = DEFAULT_RANKING_WEIGHTS

    app = FastAPI(
        title="Kelley MSIS Career Intelligence (demo)",
        version=APP_VERSION,
        docs_url="/api/docs",
        openapi_url="/api/openapi.json",
    )

    def _query(
        track: str | None = None,
        concentration: list[str] | None = None,
        role: list[str] | None = None,
        source: list[str] | None = None,
        q: str | None = None,
        location: str | None = None,
        remote: bool = False,
        sponsorship: bool = False,
    ) -> JobQuery:
        return JobQuery(
            track=track,
            concentrations=concentration or [],
            roles=role or [],
            sources=source or [],
            q=q,
            location=location,
            remote_only=remote,
            sponsorship_only=sponsorship,
        )

    @app.get("/api/health", response_model=HealthResponse)
    def health() -> HealthResponse:
        snapshot = repository.load()
        latest = snapshot.latest_run or {}
        return HealthResponse(
            status="ok",
            db_path=str(repository.db_path),
            db_exists=snapshot.db_exists,
            job_count=len(snapshot.entries),
            latest_run_at=(
                str(latest.get("completed_at")) if latest.get("completed_at") else None
            ),
        )

    @app.get("/api/stats", response_model=StatsResponse)
    def stats() -> StatsResponse:
        snapshot = repository.load()
        return compute_stats(
            snapshot.entries,
            snapshot.latest_run,
            db_exists=snapshot.db_exists,
        )

    @app.get("/api/jobs", response_model=JobsResponse)
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
    ) -> JobsResponse:
        snapshot = repository.load()
        query = _query(
            track, concentration, role, source, q, location, remote, sponsorship
        )
        filtered = apply_filters(snapshot.entries, query)
        # Facets reflect the current track + search so sidebar counts stay
        # meaningful while individual facet groups are being toggled.
        facet_entries = apply_filters(
            snapshot.entries,
            JobQuery(track=query.track, q=query.q),
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

    @app.get("/api/jobs/{job_key}", response_model=JobDetail)
    def get_job(job_key: str) -> JobDetail:
        snapshot = repository.load()
        for key, job in snapshot.entries:
            if key == job_key:
                return job_detail(key, job)
        raise HTTPException(status_code=404, detail=f"Unknown job: {job_key}")

    @app.get("/api/posts", response_model=PostsResponse)
    def list_posts(
        concentration: Annotated[list[str] | None, Query()] = None,
        company: str | None = None,
        q: str | None = None,
        sort: str | None = None,
        limit: Annotated[int, Query(ge=1, le=500)] = 60,
        offset: Annotated[int, Query(ge=0)] = 0,
    ) -> PostsResponse:
        snapshot = post_repository.load()
        query = PostQuery(concentrations=concentration or [], company=company, q=q)
        filtered = apply_post_filters(snapshot.posts, query)
        # Facets reflect the current search so sidebar counts stay meaningful
        # while individual concentration filters are toggled.
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

    @app.get("/api/posts/stats", response_model=PostStatsResponse)
    def post_stats() -> PostStatsResponse:
        snapshot = post_repository.load()
        return compute_post_stats(
            snapshot.posts,
            db_exists=snapshot.db_exists,
            latest_post_at=snapshot.latest_post_at,
        )

    @app.get("/api/posts/{post_key}", response_model=PostDetail)
    def get_post(post_key: str) -> PostDetail:
        snapshot = post_repository.load()
        for post in snapshot.posts:
            if post.post_key == post_key:
                return post_detail(post)
        raise HTTPException(status_code=404, detail=f"Unknown post: {post_key}")

    @app.get("/api/profiles", response_model=list[ProfileSummary])
    def list_profiles() -> list[ProfileSummary]:
        return [
            _profile_summary(student_id, profile)
            for student_id, profile in profiles.items()
        ]

    @app.get("/api/profiles/{student_id}/matches", response_model=MatchesResponse)
    def profile_matches(
        student_id: str,
        track: str | None = None,
        concentration: Annotated[list[str] | None, Query()] = None,
        role: Annotated[list[str] | None, Query()] = None,
        source: Annotated[list[str] | None, Query()] = None,
        q: str | None = None,
        location: str | None = None,
        remote: bool = False,
        sponsorship: bool = False,
        limit: Annotated[int, Query(ge=1, le=500)] = 60,
        offset: Annotated[int, Query(ge=0)] = 0,
    ) -> MatchesResponse:
        profile = profiles.get(student_id)
        if profile is None:
            raise HTTPException(
                status_code=404, detail=f"Unknown profile: {student_id}"
            )
        snapshot = repository.load()
        query = _query(
            track, concentration, role, source, q, location, remote, sponsorship
        )
        filtered = apply_filters(snapshot.entries, query)
        key_by_job = {id(job): job_key for job_key, job in filtered}
        matches = rank_jobs_for_student(
            profile,
            [job for _job_key, job in filtered],
            ranking_weights,
        )
        page = matches[offset : offset + limit]
        return MatchesResponse(
            profile=_profile_summary(student_id, profile),
            total=len(matches),
            matches=[
                RankedJob(
                    job=job_card(key_by_job[id(match.job)], match.job),
                    score=round(match.score, 2),
                    reasons=match.reasons,
                    score_breakdown=match.metadata.get("score_breakdown", {}),
                )
                for match in page
            ],
        )

    @app.get("/api/meta/taxonomy", response_model=TaxonomyResponse)
    def taxonomy() -> TaxonomyResponse:
        return TaxonomyResponse(
            concentrations=[
                TaxonomyEntry(name=name, code=CONCENTRATION_CODES.get(name, name))
                for name in MSIS_CONCENTRATIONS
            ],
            roles=list(MSIS_TARGET_ROLES),
            tracks=list(CAREER_TRACKS),
        )

    @app.get("/", include_in_schema=False)
    def index() -> FileResponse:
        return FileResponse(STATIC_DIR / "index.html")

    app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

    return app


app = create_app()

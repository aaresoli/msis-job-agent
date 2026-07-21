"""Pure filtering, faceting, and presentation logic for the Posts API.

Mirrors :mod:`hope_job_agent.dashboard.service` (which handles jobs) but for
LinkedIn hiring posts. Everything operates on in-memory ``MarketPostView``
objects so it is unit-testable without HTTP or a database. The repository layer
(:mod:`hope_job_agent.dashboard.db`) builds these views from ``market_posts``
rows plus their cited ``market_signals``.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta

from hope_job_agent.classification.taxonomy import (
    CONCENTRATION_CODES,
    MSIS_CONCENTRATIONS,
)

from .schemas import (
    FacetCount,
    PostCard,
    PostDetail,
    PostsFacets,
    PostSignal,
    PostStatsResponse,
)

# Posts older than this never surface in the dashboard. Posts with no parseable
# publish date are kept (we can't tell their age). Matches the jobs feed.
MAX_POST_AGE_DAYS = 30

_EXCERPT_CHARS = 320
_TOP_COMPANIES = 12


@dataclass(frozen=True)
class PostSignalView:
    """An LLM-extracted hiring signal citing a post."""

    topic: str
    summary: str
    company_name: str | None = None
    role_tags: list[str] = field(default_factory=list)
    confidence: float | None = None


@dataclass(frozen=True)
class MarketPostView:
    """In-memory read model for one hiring post plus its signals."""

    post_key: str
    author_name: str | None
    company_name: str | None
    content: str
    source_url: str
    published_at: datetime | None = None
    relevance_score: float | None = None
    matched_keywords: list[str] = field(default_factory=list)
    concentration_hints: list[str] = field(default_factory=list)
    career_stage: str | None = None
    signals: list[PostSignalView] = field(default_factory=list)


@dataclass(frozen=True)
class PostQuery:
    """Normalized filter parameters for /api/posts."""

    concentrations: list[str] = field(default_factory=list)
    company: str | None = None
    q: str | None = None


def apply_post_filters(
    posts: list[MarketPostView], query: PostQuery
) -> list[MarketPostView]:
    """Filter posts by every populated field of the query."""

    selected_concentrations = {value.casefold() for value in query.concentrations}
    company_query = (query.company or "").casefold().strip()
    text_query = (query.q or "").casefold().strip()
    max_age_cutoff = datetime.now(UTC) - timedelta(days=MAX_POST_AGE_DAYS)

    results: list[MarketPostView] = []
    for post in posts:
        published = _as_aware(post.published_at)
        if published is not None and published < max_age_cutoff:
            continue
        if selected_concentrations and not (
            selected_concentrations
            & {hint.casefold() for hint in post.concentration_hints}
        ):
            continue
        if company_query and company_query not in (post.company_name or "").casefold():
            continue
        if text_query and not _matches_text(post, text_query):
            continue
        results.append(post)
    return results


def sort_posts(posts: list[MarketPostView], sort: str | None) -> list[MarketPostView]:
    """Sort filtered posts: recent (default) or relevance."""

    if sort == "relevance":
        return sorted(
            posts,
            key=lambda post: (
                -(post.relevance_score or 0.0),
                _date_sort_value(post),
            ),
        )
    return sorted(
        posts,
        key=lambda post: (
            _date_sort_value(post),
            -(post.relevance_score or 0.0),
        ),
    )


def compute_post_facets(posts: list[MarketPostView]) -> PostsFacets:
    """Facet counts for the Posts sidebar."""

    concentration_counts: Counter[str] = Counter()
    company_counts: Counter[str] = Counter()
    for post in posts:
        for hint in post.concentration_hints:
            concentration_counts[hint] += 1
        if post.company_name:
            company_counts[post.company_name] += 1

    return PostsFacets(
        concentrations=[
            FacetCount(
                name=name,
                code=CONCENTRATION_CODES.get(name),
                count=concentration_counts.get(name, 0),
            )
            for name in MSIS_CONCENTRATIONS
        ],
        companies=[
            FacetCount(name=name, count=count)
            for name, count in sorted(
                company_counts.items(), key=lambda item: (-item[1], item[0])
            )[:_TOP_COMPANIES]
        ],
    )


def compute_post_stats(
    posts: list[MarketPostView],
    *,
    db_exists: bool,
    latest_post_at: datetime | None = None,
) -> PostStatsResponse:
    """Header-strip stats for the Posts view."""

    facets = compute_post_facets(posts)
    week_ago = datetime.now(UTC) - timedelta(days=7)
    new_this_week = sum(
        1
        for post in posts
        if (published := _as_aware(post.published_at)) is not None
        and published >= week_ago
    )
    with_opportunity = sum(1 for post in posts if post.signals)
    company_count = len(
        {post.company_name.casefold() for post in posts if post.company_name}
    )
    return PostStatsResponse(
        db_exists=db_exists,
        total_posts=len(posts),
        company_count=company_count,
        new_this_week=new_this_week,
        with_opportunity=with_opportunity,
        by_concentration=facets.concentrations,
        latest_post_at=(latest_post_at.isoformat() if latest_post_at else None),
    )


def post_card(post: MarketPostView) -> PostCard:
    """Project a post into the card shape the grid renders."""

    return PostCard(
        post_key=post.post_key,
        author_name=post.author_name,
        company_name=post.company_name,
        content_excerpt=_excerpt(post.content),
        source_url=post.source_url,
        published_at=(post.published_at.isoformat() if post.published_at else None),
        relevance_score=post.relevance_score,
        concentration_tags=list(post.concentration_hints),
        concentration_codes=[
            CONCENTRATION_CODES.get(hint, hint) for hint in post.concentration_hints
        ],
        matched_keywords=list(post.matched_keywords),
        has_signal=bool(post.signals),
        signal_summary=(post.signals[0].summary if post.signals else None),
    )


def post_detail(post: MarketPostView) -> PostDetail:
    """Project a post into the drawer shape, including full content + signals."""

    card = post_card(post)
    return PostDetail(
        **card.model_dump(),
        content=post.content,
        career_stage=post.career_stage,
        signals=[
            PostSignal(
                topic=signal.topic,
                summary=signal.summary,
                company_name=signal.company_name,
                role_tags=list(signal.role_tags),
                confidence=signal.confidence,
            )
            for signal in post.signals
        ],
    )


def _matches_text(post: MarketPostView, text_query: str) -> bool:
    haystack = " ".join(
        [post.content, post.author_name or "", post.company_name or ""]
    ).casefold()
    return text_query in haystack


def _excerpt(content: str) -> str:
    text = " ".join(content.split())
    if len(text) <= _EXCERPT_CHARS:
        return text
    return text[:_EXCERPT_CHARS].rstrip() + "…"


def _as_aware(value: datetime | None) -> datetime | None:
    """Return a timezone-aware datetime (assume UTC when naive)."""

    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value


def _date_sort_value(post: MarketPostView) -> float:
    published = _as_aware(post.published_at)
    if published is None:
        return 0.0
    return -published.timestamp()

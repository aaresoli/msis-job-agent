"""Unit coverage for the dashboard Posts service (pure functions)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from hope_job_agent.discovery.posts_service import (
    MarketPostView,
    PostQuery,
    PostSignalView,
    apply_post_filters,
    compute_post_facets,
    compute_post_stats,
    post_card,
    post_detail,
    sort_posts,
)

pytestmark = pytest.mark.unit


def _post(
    key: str,
    *,
    author: str | None = "Jane Doe",
    company: str | None = "Cubit Capital",
    content: str = "We're hiring data analysts.",
    days_ago: int | None = 1,
    score: float | None = 4.0,
    hints: list[str] | None = None,
    signals: list[PostSignalView] | None = None,
) -> MarketPostView:
    published = (
        datetime.now(UTC) - timedelta(days=days_ago) if days_ago is not None else None
    )
    return MarketPostView(
        post_key=key,
        author_name=author,
        company_name=company,
        content=content,
        source_url=f"https://linkedin.com/posts/{key}",
        published_at=published,
        relevance_score=score,
        matched_keywords=["data analyst"],
        concentration_hints=hints if hints is not None else ["Data Analytics and AI"],
        career_stage="early_career",
        signals=signals or [],
    )


def test_recency_filter_drops_stale_posts() -> None:
    fresh = _post("a", days_ago=2)
    stale = _post("b", days_ago=90)
    undated = _post("c", days_ago=None)

    kept = apply_post_filters([fresh, stale, undated], PostQuery())

    keys = {post.post_key for post in kept}
    assert keys == {"a", "c"}  # stale dropped, undated kept


def test_concentration_filter_matches_hints() -> None:
    da = _post("a", hints=["Data Analytics and AI"])
    cyber = _post("b", hints=["Cybersecurity and Risk Analytics"])

    kept = apply_post_filters(
        [da, cyber], PostQuery(concentrations=["Cybersecurity and Risk Analytics"])
    )
    assert [post.post_key for post in kept] == ["b"]


def test_company_and_text_filters() -> None:
    a = _post("a", company="Acme", content="Hiring a data analyst at Acme")
    b = _post("b", company="Globex", content="Join our analytics team at Globex")

    by_company = apply_post_filters([a, b], PostQuery(company="glob"))
    assert [p.post_key for p in by_company] == ["b"]
    by_text = apply_post_filters([a, b], PostQuery(q="acme"))
    assert [p.post_key for p in by_text] == ["a"]


def test_sort_recent_and_relevance() -> None:
    older_high = _post("a", days_ago=5, score=9.0)
    newer_low = _post("b", days_ago=1, score=1.0)

    recent = sort_posts([older_high, newer_low], "recent")
    assert [p.post_key for p in recent] == ["b", "a"]

    relevance = sort_posts([older_high, newer_low], "relevance")
    assert [p.post_key for p in relevance] == ["a", "b"]


def test_facets_and_stats() -> None:
    posts = [
        _post("a", company="Acme", hints=["Data Analytics and AI"]),
        _post("b", company="Acme", hints=["Cybersecurity and Risk Analytics"]),
        _post(
            "c",
            company="Globex",
            hints=["Data Analytics and AI"],
            signals=[
                PostSignalView(topic="Hiring", summary="3 analysts", confidence=0.8)
            ],
        ),
    ]

    facets = compute_post_facets(posts)
    da = next(f for f in facets.concentrations if f.name == "Data Analytics and AI")
    assert da.count == 2
    assert facets.companies[0].name == "Acme"  # 2 posts, ranked first

    stats = compute_post_stats(posts, db_exists=True)
    assert stats.total_posts == 3
    assert stats.company_count == 2
    assert stats.with_opportunity == 1
    assert stats.new_this_week == 3


def test_post_card_and_detail_projection() -> None:
    signal = PostSignalView(
        topic="Data hiring",
        summary="Hiring 3 junior data analysts in Chicago.",
        company_name="Cubit Capital",
        role_tags=["data analyst"],
        confidence=0.75,
    )
    view = _post("a", content="  We're   hiring\n\nApply now.  ", signals=[signal])

    card = post_card(view)
    assert card.post_key == "a"
    assert card.has_signal is True
    assert card.signal_summary == "Hiring 3 junior data analysts in Chicago."
    assert "Data Analytics and AI" in card.concentration_tags
    assert card.concentration_codes  # mapped to codes
    assert card.published_at is not None  # ISO string

    detail = post_detail(view)
    assert detail.content == "  We're   hiring\n\nApply now.  "
    assert len(detail.signals) == 1
    assert detail.signals[0].topic == "Data hiring"
    assert detail.career_stage == "early_career"


def test_excerpt_is_truncated() -> None:
    long_post = _post("a", content="word " * 200)
    card = post_card(long_post)
    assert card.content_excerpt.endswith("…")
    assert len(card.content_excerpt) <= 321

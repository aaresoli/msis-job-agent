"""Coverage for the scheduled LinkedIn-posts refresh Celery task."""

from __future__ import annotations

from contextlib import contextmanager

import pytest

from hope_job_agent.workers import tasks

pytestmark = pytest.mark.unit


@contextmanager
def _fake_session_scope(_factory):  # noqa: ANN001
    yield object()


@pytest.fixture(autouse=True)
def _stub_session(monkeypatch: pytest.MonkeyPatch) -> None:
    # Avoid touching Postgres: the task opens session_scope(_factory()).
    monkeypatch.setattr(tasks, "session_factory", lambda: None)
    monkeypatch.setattr(tasks, "session_scope", _fake_session_scope)


def test_refresh_posts_ingests_and_triggers_pulse(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[dict] = []

    def fake_ingest(session, **kwargs):  # noqa: ANN001, ANN003
        calls.append(kwargs)
        return {
            "inserted": 2,
            "updated": 1,
            "unchanged": 0,
            "fetch": {},
            "warnings": [],
        }

    enqueued: list[bool] = []

    class _Pulse:
        def apply_async(self, **kwargs):  # noqa: ANN003, ANN201
            enqueued.append(True)

    monkeypatch.setattr(tasks, "ingest_market_posts", fake_ingest)
    monkeypatch.setattr(tasks, "refresh_market_pulse", _Pulse())

    outcome = tasks.refresh_posts.apply(
        kwargs={"dataset_id": "ds123", "max_items": 10}
    ).get()

    assert outcome["status"] == "completed"
    assert outcome["inserted"] == 2
    assert calls[0]["dataset_id"] == "ds123"
    assert calls[0]["max_items"] == 10
    assert enqueued == [True]  # new posts trigger market-pulse


def test_refresh_posts_skips_pulse_when_nothing_changed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fake_ingest(session, **kwargs):  # noqa: ANN001, ANN003
        return {
            "inserted": 0,
            "updated": 0,
            "unchanged": 5,
            "fetch": {},
            "warnings": [],
        }

    enqueued: list[bool] = []

    class _Pulse:
        def apply_async(self, **kwargs):  # noqa: ANN003, ANN201
            enqueued.append(True)

    monkeypatch.setattr(tasks, "ingest_market_posts", fake_ingest)
    monkeypatch.setattr(tasks, "refresh_market_pulse", _Pulse())

    outcome = tasks.refresh_posts.apply(kwargs={"dataset_id": "ds123"}).get()

    assert outcome["status"] == "completed"
    assert outcome["unchanged"] == 5
    assert enqueued == []  # no new/updated posts → no pulse

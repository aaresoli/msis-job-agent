"""Coverage for the refresh-all orchestrator task."""

from __future__ import annotations

import uuid
from contextlib import contextmanager
from pathlib import Path

import pytest

from hope_job_agent.pipeline.run_mvp import MvpPipelineError, MvpPipelineResult
from hope_job_agent.workers import tasks

pytestmark = pytest.mark.unit


@contextmanager
def _fake_session_scope(_factory):  # noqa: ANN001
    yield object()


@contextmanager
def _uncontended_lock(_key, _ttl):  # noqa: ANN001
    """Stand in for the Redis single-flight guard.

    These are unit tests with no broker. Letting the real lock run would make
    them require Redis to assert things about sweep bookkeeping; the lock's own
    behaviour is covered in tests/test_single_flight.py.
    """

    yield


class _FakeSourceRuns:
    """Stand-in for SourceRunRepository that records parent-run bookkeeping."""

    started: list[tuple[str, dict]] = []
    finished: list[tuple[uuid.UUID, dict]] = []
    failed: list[tuple[uuid.UUID, str]] = []

    def __init__(self, session) -> None:  # noqa: ANN001
        del session

    def start_run(self, source_name, *, run_id=None, metadata=None):  # noqa: ANN001
        del run_id
        _FakeSourceRuns.started.append((source_name, metadata or {}))
        return type("_Run", (), {"id": uuid.UUID(int=1)})()

    def finish_run(self, run_id, *, summary):  # noqa: ANN001
        _FakeSourceRuns.finished.append((run_id, summary))

    def fail_run(self, run_id, error):  # noqa: ANN001
        _FakeSourceRuns.failed.append((run_id, error))


@pytest.fixture(autouse=True)
def _stub_infrastructure(monkeypatch: pytest.MonkeyPatch) -> None:
    _FakeSourceRuns.started = []
    _FakeSourceRuns.finished = []
    _FakeSourceRuns.failed = []
    monkeypatch.setattr(tasks, "session_factory", lambda: None)
    monkeypatch.setattr(tasks, "session_scope", _fake_session_scope)
    monkeypatch.setattr(tasks, "SourceRunRepository", _FakeSourceRuns)
    monkeypatch.setattr(tasks, "single_flight", _uncontended_lock)


def _pipeline_result(source: str) -> MvpPipelineResult:
    return MvpPipelineResult(
        output_path=Path("jobs.json"),
        summary_path=Path("jobs.summary.json"),
        rows=[],
        summary={
            "run_id": f"run-{source}",
            "raw_count": 10,
            "unique_count": 8,
            "duplicate_count": 2,
            "warnings": [],
        },
    )


def _stub_posts(monkeypatch: pytest.MonkeyPatch, **counts) -> list[dict]:
    calls: list[dict] = []

    def fake_ingest(session, **kwargs):  # noqa: ANN001, ANN003
        calls.append(kwargs)
        return {
            "source": "apify_linkedin_posts",
            "fetch": {"raw_count": 7},
            "warnings": [],
            "inserted": 0,
            "updated": 0,
            "unchanged": 0,
            **counts,
        }

    monkeypatch.setattr(tasks, "ingest_market_posts", fake_ingest)
    return calls


def test_refresh_all_runs_every_source_then_signals(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    order: list[str] = []

    def fake_pipeline(**kwargs):  # noqa: ANN003, ANN202
        order.append(kwargs["source_name"])
        return _pipeline_result(kwargs["source_name"])

    monkeypatch.setattr(tasks, "run_mvp_pipeline", fake_pipeline)
    _stub_posts(monkeypatch, inserted=3, updated=1)

    class _Pulse:
        def run(self):  # noqa: ANN201
            order.append("signals")
            return {"status": "ready", "signals": 4}

        def apply_async(self, **kwargs):  # noqa: ANN003, ANN201
            raise AssertionError("the sweep runs the pulse itself, once")

    monkeypatch.setattr(tasks, "refresh_market_pulse", _Pulse())

    outcome = tasks.refresh_all.apply().get()

    # Jobs first, posts next, signals last (posts must land before extraction).
    assert order == ["apify_linkedin", "company_careers", "signals"]
    assert outcome["status"] == "completed"
    assert outcome["errors"] == []
    assert outcome["signals"] == {"status": "ready", "signals": 4}
    assert [result["kind"] for result in outcome["sources"]] == [
        "jobs",
        "jobs",
        "posts",
    ]

    # One parent run, aggregating both tables' fetch counts.
    assert [source for source, _ in _FakeSourceRuns.started] == ["refresh_all"]
    _, summary = _FakeSourceRuns.finished[0]
    assert summary["raw_count"] == 27  # 10 + 10 jobs + 7 posts
    assert summary["duplicate_count"] == 4
    assert summary["errors"] == []
    assert _FakeSourceRuns.failed == []


def test_refresh_all_records_a_failed_source_and_keeps_going(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fake_pipeline(**kwargs):  # noqa: ANN003, ANN202
        if kwargs["source_name"] == "apify_linkedin":
            raise MvpPipelineError("apify token rejected")
        return _pipeline_result(kwargs["source_name"])

    monkeypatch.setattr(tasks, "run_mvp_pipeline", fake_pipeline)
    _stub_posts(monkeypatch, inserted=1)
    monkeypatch.setattr(
        tasks,
        "refresh_market_pulse",
        type("_Pulse", (), {"run": lambda self: {"status": "ready", "signals": 1}})(),
    )
    monkeypatch.setattr(tasks, "_record_failed_source_run", lambda source, error: None)

    outcome = tasks.refresh_all.apply().get()

    assert outcome["status"] == "partial_success"
    assert outcome["errors"] == ["apify_linkedin: apify token rejected"]
    by_source = {result["source"]: result for result in outcome["sources"]}
    assert by_source["apify_linkedin"]["status"] == "failed"
    assert by_source["company_careers"]["status"] == "completed"

    _, summary = _FakeSourceRuns.finished[0]
    assert summary["raw_count"] == 17  # the failed source contributes nothing
    assert _FakeSourceRuns.failed == []  # one source survived → partial, not failed


def test_refresh_all_marks_the_parent_failed_when_nothing_succeeds(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fake_pipeline(**kwargs):  # noqa: ANN003, ANN202
        raise MvpPipelineError("every board timed out")

    def fake_ingest(session, **kwargs):  # noqa: ANN001, ANN003
        raise RuntimeError("apify dataset missing")

    monkeypatch.setattr(tasks, "run_mvp_pipeline", fake_pipeline)
    monkeypatch.setattr(tasks, "ingest_market_posts", fake_ingest)
    monkeypatch.setattr(tasks, "_record_failed_source_run", lambda source, error: None)

    outcome = tasks.refresh_all.apply().get()

    assert outcome["status"] == "failed"
    assert len(outcome["errors"]) == 3
    assert outcome["signals"] is None
    assert len(_FakeSourceRuns.failed) == 1


def test_refresh_all_skips_signals_when_no_posts_changed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        tasks, "run_mvp_pipeline", lambda **kwargs: _pipeline_result("x")
    )
    _stub_posts(monkeypatch, unchanged=7)
    monkeypatch.setattr(
        tasks,
        "refresh_market_pulse",
        type(
            "_Pulse",
            (),
            {"run": lambda self: pytest.fail("pulse ran with no new posts")},
        )(),
    )

    outcome = tasks.refresh_all.apply().get()

    assert outcome["status"] == "completed"
    assert outcome["signals"] is None


def test_refresh_all_can_skip_posts_and_target_one_source(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    seen: list[dict] = []

    def fake_pipeline(**kwargs):  # noqa: ANN003, ANN202
        seen.append(kwargs)
        return _pipeline_result(kwargs["source_name"])

    monkeypatch.setattr(tasks, "run_mvp_pipeline", fake_pipeline)

    outcome = tasks.refresh_all.apply(
        kwargs={
            "sources": ["company_careers"],
            "include_posts": False,
            "limit": 25,
            "full_refresh": True,
        }
    ).get()

    assert [result["source"] for result in outcome["sources"]] == ["company_careers"]
    assert seen[0]["limit"] == 25
    assert seen[0]["full_refresh"] is True
    assert seen[0]["storage"] == "postgres"

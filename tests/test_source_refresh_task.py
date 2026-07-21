"""Coverage for the scheduled source-refresh Celery task."""

from __future__ import annotations

from pathlib import Path

import pytest

from hope_job_agent.pipeline.run_mvp import MvpPipelineError, MvpPipelineResult
from hope_job_agent.workers import tasks


def _result(**summary_overrides) -> MvpPipelineResult:
    summary = {
        "run_id": "run-1",
        "raw_count": 12,
        "unique_count": 10,
        "warnings": ["one warning"],
        **summary_overrides,
    }
    return MvpPipelineResult(
        output_path=Path("jobs.json"),
        summary_path=Path("jobs.summary.json"),
        rows=[],
        summary=summary,
    )


def test_refresh_rejects_sources_outside_the_scheduler_allowlist() -> None:
    outcome = tasks.refresh_source.apply(args=["kelleylink_excel"]).get()

    assert outcome["status"] == "rejected"
    assert "not refreshable" in outcome["reason"]


def test_refresh_reports_disabled_for_unapproved_sources(monkeypatch) -> None:
    monkeypatch.setattr(
        tasks, "REFRESHABLE_SOURCES", frozenset({"company_careers", "ksbit_denodo"})
    )

    outcome = tasks.refresh_source.apply(args=["ksbit_denodo"]).get()

    assert outcome["status"] == "disabled"
    assert "ksbit_denodo" in outcome["reason"]


def test_refresh_runs_the_pipeline_into_postgres_and_summarizes(monkeypatch) -> None:
    calls: list[dict] = []

    def fake_pipeline(**kwargs):  # noqa: ANN003, ANN202
        calls.append(kwargs)
        return _result()

    monkeypatch.setattr(tasks, "run_mvp_pipeline", fake_pipeline)

    outcome = tasks.refresh_source.apply(
        args=["company_careers"], kwargs={"limit": 5}
    ).get()

    assert outcome["status"] == "completed"
    assert outcome["run_id"] == "run-1"
    assert outcome["raw_count"] == 12
    assert outcome["unique_count"] == 10
    assert outcome["warnings"] == 1

    call = calls[0]
    assert call["source_name"] == "company_careers"
    assert call["storage"] == "postgres"
    assert call["profiles_path"] is None
    assert call["limit"] == 5
    assert call["full_refresh"] is False
    # The runner writes artifacts to a scratch directory that is cleaned up.
    assert call["output_path"].name == "jobs.json"
    assert not call["output_path"].parent.exists()


def test_refresh_records_a_failed_source_run_before_reraising(monkeypatch) -> None:
    recorded: list[tuple[str, str]] = []

    def fake_pipeline(**kwargs):  # noqa: ANN003, ANN202
        del kwargs
        raise MvpPipelineError("every company failed")

    monkeypatch.setattr(tasks, "run_mvp_pipeline", fake_pipeline)
    monkeypatch.setattr(
        tasks,
        "_record_failed_source_run",
        lambda source, error: recorded.append((source, error)),
    )

    with pytest.raises(MvpPipelineError, match="every company failed"):
        tasks.refresh_source.apply(args=["company_careers"]).get()

    assert recorded == [("company_careers", "every company failed")]

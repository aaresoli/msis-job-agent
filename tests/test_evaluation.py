from pathlib import Path

import pytest

from hope_job_agent.evaluation.evaluate import evaluate_fixture


def test_evaluate_fixture_reports_metrics():
    report = evaluate_fixture(Path("tests/fixtures/labelled_postings.json"))

    assert report.record_count == 4
    assert report.role_accuracy >= 0.75
    assert report.concentration_accuracy >= 0.75
    assert report.ranking_relevance_at_3 == 1.0


def test_evaluate_fixture_fails_clearly_for_missing_dataset(tmp_path):
    with pytest.raises(FileNotFoundError, match="Labelled evaluation dataset"):
        evaluate_fixture(tmp_path / "missing.json")

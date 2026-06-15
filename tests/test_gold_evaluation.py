from hope_job_agent.datasets.gold_postings import load_gold_postings
from hope_job_agent.evaluation.gold_set import (
    evaluate_classifier,
    evaluate_ranking,
)


def test_classifier_evaluation_compares_predictions_to_gold_labels():
    evaluation = evaluate_classifier(load_gold_postings())

    assert evaluation.total >= 10
    assert 0.0 <= evaluation.role_accuracy <= 1.0
    assert 0.0 <= evaluation.concentration_accuracy <= 1.0
    assert 0.0 <= evaluation.exact_match_accuracy <= 1.0
    assert all(result.posting_id.startswith("gold-") for result in evaluation.results)


def test_ranking_evaluation_compares_scores_to_relevance_labels():
    evaluation = evaluate_ranking(load_gold_postings())

    assert evaluation.total >= 10
    assert 0.0 <= evaluation.pairwise_ordering_accuracy <= 1.0
    assert set(evaluation.mean_score_by_relevance) >= {"high", "medium", "low"}
    assert [result.rank for result in evaluation.top_ranked] == list(
        range(1, evaluation.total + 1)
    )

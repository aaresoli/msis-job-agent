"""Print classifier and ranking metrics for the gold job posting dataset."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from hope_job_agent.datasets.gold_postings import load_gold_postings
from hope_job_agent.evaluation.gold_set import evaluate_classifier, evaluate_ranking


def main() -> None:
    postings = load_gold_postings()
    classification = evaluate_classifier(postings)
    ranking = evaluate_ranking(postings)

    print("Gold set evaluation")
    print(f"Postings: {classification.total}")
    print(f"Role accuracy: {classification.role_accuracy:.1%}")
    print(f"Concentration accuracy: {classification.concentration_accuracy:.1%}")
    print(
        "Exact role+concentration accuracy: "
        f"{classification.exact_match_accuracy:.1%}"
    )
    print(
        "Ranking pairwise relevance accuracy: "
        f"{ranking.pairwise_ordering_accuracy:.1%}"
    )
    print("Mean ranking score by relevance:")
    for relevance, score in ranking.mean_score_by_relevance.items():
        print(f"  {relevance}: {score:.2f}")

    if classification.misses:
        print("Classifier misses:")
        for result in classification.misses:
            print(
                f"  {result.posting_id}: expected "
                f"{result.expected_role} / {result.expected_concentration}; "
                f"predicted {result.predicted_roles} / "
                f"{result.predicted_concentrations}"
            )


if __name__ == "__main__":
    main()

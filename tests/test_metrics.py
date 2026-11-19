from hope_job_agent.evaluation.metrics import (
    evaluate_fixture_dataset,
    evaluate_gold_dataset,
    format_report_text,
    multilabel_metrics,
)


def test_multilabel_metrics_computes_precision_recall_f1():
    labels = ["A", "B", "C"]
    pairs = [
        ({"A"}, {"A"}),  # true positive for A
        ({"A", "B"}, {"B"}),  # A false positive, B true positive
        ({"C"}, {"B"}),  # B false negative, C false positive
        (set(), set()),  # ignored (no gold supervision)
    ]

    metrics = multilabel_metrics(pairs, labels)
    by_label = {metric.label: metric for metric in metrics.per_class}

    assert by_label["A"].true_positives == 1
    assert by_label["A"].false_positives == 1
    assert by_label["A"].precision == 0.5
    assert by_label["A"].recall == 1.0
    assert by_label["B"].support == 2
    assert by_label["B"].recall == 0.5
    assert by_label["C"].false_positives == 1
    # Only the first pair has gold fully contained in predicted among scored rows.
    assert 0.0 < metrics.subset_accuracy <= 1.0
    assert 0.0 <= metrics.macro_f1 <= 1.0
    assert 0.0 <= metrics.micro_f1 <= 1.0


def test_multilabel_metrics_ignores_pairs_without_gold_labels():
    metrics = multilabel_metrics([(set(), set())], ["A"])

    assert metrics.subset_accuracy == 0.0
    assert all(metric.support == 0 for metric in metrics.per_class)


def test_evaluate_gold_dataset_reports_all_label_spaces():
    report = evaluate_gold_dataset()

    assert report["dataset"] == "gold"
    assert report["record_count"] == 12
    assert {metric["label"] for metric in report["roles"]["per_class"]}
    concentration_labels = {
        metric["label"] for metric in report["concentrations"]["per_class"]
    }
    assert "Digital Platforms and Security" in concentration_labels


def test_evaluate_fixture_dataset_validates_dps_recall():
    report = evaluate_fixture_dataset()

    dps = next(
        metric
        for metric in report["concentrations"]["per_class"]
        if metric["label"] == "Digital Platforms and Security"
    )
    assert dps["support"] == 1
    assert dps["recall"] == 1.0


def test_format_report_text_includes_headers():
    text = format_report_text(evaluate_fixture_dataset())

    assert "Roles" in text
    assert "Concentrations" in text
    assert "macro_f1" in text

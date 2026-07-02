"""Per-class precision/recall/F1 harness for classifier calibration.

This is the tool to run when a real labeled KelleyLink/KSBIT export becomes
available: it reports, per role and per concentration, how the deterministic
classifier performs against manual labels so keyword lists can be tuned with
evidence rather than guesswork. It is deterministic and uses no LLM.
"""

from __future__ import annotations

import json
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from hope_job_agent.classification.classifier import classify_job
from hope_job_agent.classification.taxonomy import (
    MSIS_CONCENTRATIONS,
    MSIS_TARGET_ROLES,
)
from hope_job_agent.datasets.gold_postings import DATASET_PATH, load_gold_postings
from hope_job_agent.models.job import JobPosting

FIXTURE_PATH = Path("tests/fixtures/labelled_postings.json")

LabelPair = tuple[set[str], set[str]]


@dataclass(frozen=True)
class ClassMetric:
    """Precision/recall/F1 for a single label."""

    label: str
    support: int
    true_positives: int
    false_positives: int
    false_negatives: int

    @property
    def precision(self) -> float:
        denominator = self.true_positives + self.false_positives
        return self.true_positives / denominator if denominator else 0.0

    @property
    def recall(self) -> float:
        denominator = self.true_positives + self.false_negatives
        return self.true_positives / denominator if denominator else 0.0

    @property
    def f1(self) -> float:
        precision = self.precision
        recall = self.recall
        if precision + recall == 0:
            return 0.0
        return 2 * precision * recall / (precision + recall)

    def as_dict(self) -> dict[str, Any]:
        return {
            "label": self.label,
            "support": self.support,
            "true_positives": self.true_positives,
            "false_positives": self.false_positives,
            "false_negatives": self.false_negatives,
            "precision": round(self.precision, 3),
            "recall": round(self.recall, 3),
            "f1": round(self.f1, 3),
        }


@dataclass(frozen=True)
class TaxonomyMetrics:
    """Aggregate multi-label metrics for one label space (roles or concentrations)."""

    per_class: list[ClassMetric]
    subset_accuracy: float

    @property
    def labels_with_support(self) -> list[ClassMetric]:
        return [metric for metric in self.per_class if metric.support > 0]

    @property
    def macro_f1(self) -> float:
        supported = self.labels_with_support
        if not supported:
            return 0.0
        return sum(metric.f1 for metric in supported) / len(supported)

    @property
    def micro_f1(self) -> float:
        true_positives = sum(metric.true_positives for metric in self.per_class)
        false_positives = sum(metric.false_positives for metric in self.per_class)
        false_negatives = sum(metric.false_negatives for metric in self.per_class)
        precision_den = true_positives + false_positives
        recall_den = true_positives + false_negatives
        precision = true_positives / precision_den if precision_den else 0.0
        recall = true_positives / recall_den if recall_den else 0.0
        if precision + recall == 0:
            return 0.0
        return 2 * precision * recall / (precision + recall)

    def as_dict(self) -> dict[str, Any]:
        return {
            "subset_accuracy": round(self.subset_accuracy, 3),
            "macro_f1": round(self.macro_f1, 3),
            "micro_f1": round(self.micro_f1, 3),
            "per_class": [metric.as_dict() for metric in self.per_class],
        }


def multilabel_metrics(
    pairs: Sequence[LabelPair],
    labels: Sequence[str],
) -> TaxonomyMetrics:
    """Compute per-class metrics from (predicted, gold) label-set pairs.

    Pairs whose gold set is empty are ignored (they carry no supervision).
    """

    scored = [(predicted, gold) for predicted, gold in pairs if gold]
    per_class: list[ClassMetric] = []
    for label in labels:
        true_positives = sum(
            1 for predicted, gold in scored if label in gold and label in predicted
        )
        false_positives = sum(
            1 for predicted, gold in scored if label in predicted and label not in gold
        )
        false_negatives = sum(
            1 for predicted, gold in scored if label in gold and label not in predicted
        )
        support = sum(1 for _, gold in scored if label in gold)
        per_class.append(
            ClassMetric(
                label=label,
                support=support,
                true_positives=true_positives,
                false_positives=false_positives,
                false_negatives=false_negatives,
            )
        )

    subset_hits = sum(1 for predicted, gold in scored if gold <= predicted)
    subset_accuracy = subset_hits / len(scored) if scored else 0.0
    return TaxonomyMetrics(per_class=per_class, subset_accuracy=subset_accuracy)


def evaluate_gold_dataset(path: Path = DATASET_PATH) -> dict[str, Any]:
    """Evaluate the classifier against the manually labeled gold postings."""

    role_pairs: list[LabelPair] = []
    concentration_pairs: list[LabelPair] = []
    for posting in load_gold_postings(path):
        job = JobPosting(
            source=posting.source,
            title=posting.title,
            company=posting.company,
            location=posting.location,
            description=posting.posting_summary,
            url=str(posting.source_url),
        )
        classification = classify_job(job)
        role_pairs.append(
            (set(classification.role_tags), {posting.manual_labels.primary_role})
        )
        concentration_pairs.append(
            (
                set(classification.concentration_tags),
                {posting.manual_labels.concentration},
            )
        )

    return _build_report("gold", role_pairs, concentration_pairs)


def evaluate_fixture_dataset(path: Path = FIXTURE_PATH) -> dict[str, Any]:
    """Evaluate the classifier against the synthetic labelled fixture."""

    payload = json.loads(path.read_text(encoding="utf-8"))
    role_pairs: list[LabelPair] = []
    concentration_pairs: list[LabelPair] = []
    for record in payload.get("postings", []):
        job = JobPosting(
            source=record["source"],
            title=record["title"],
            company=record["company"],
            location=record["location"],
            description=record["description"],
            url=record["source_url"],
        )
        classification = classify_job(job)
        role_pairs.append(
            (set(classification.role_tags), set(record.get("expected_role_tags", [])))
        )
        concentration_pairs.append(
            (
                set(classification.concentration_tags),
                set(record.get("expected_concentration_tags", [])),
            )
        )

    return _build_report("fixture", role_pairs, concentration_pairs)


def _build_report(
    dataset: str,
    role_pairs: list[LabelPair],
    concentration_pairs: list[LabelPair],
) -> dict[str, Any]:
    return {
        "dataset": dataset,
        "record_count": len(role_pairs),
        "roles": multilabel_metrics(role_pairs, MSIS_TARGET_ROLES).as_dict(),
        "concentrations": multilabel_metrics(
            concentration_pairs, MSIS_CONCENTRATIONS
        ).as_dict(),
    }


def format_report_text(report: dict[str, Any]) -> str:
    """Render a taxonomy report as a compact console table."""

    lines = [
        f"Dataset: {report['dataset']} ({report['record_count']} records)",
    ]
    for space in ("roles", "concentrations"):
        block = report[space]
        lines.append("")
        lines.append(
            f"{space.title()} — subset_acc={block['subset_accuracy']} "
            f"macro_f1={block['macro_f1']} micro_f1={block['micro_f1']}"
        )
        lines.append(f"  {'label':<34} {'sup':>3} {'P':>5} {'R':>5} {'F1':>5}")
        for metric in block["per_class"]:
            lines.append(
                f"  {metric['label']:<34} {metric['support']:>3} "
                f"{metric['precision']:>5} {metric['recall']:>5} {metric['f1']:>5}"
            )
    return "\n".join(lines)

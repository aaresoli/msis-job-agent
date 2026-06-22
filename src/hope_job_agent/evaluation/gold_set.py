"""Evaluate classifier and ranking behavior against the gold posting set."""

from dataclasses import dataclass

from hope_job_agent.classification.classifier import classify_job
from hope_job_agent.datasets.gold_postings import GoldJobPosting
from hope_job_agent.models.job import JobPosting
from hope_job_agent.models.student import StudentProfile
from hope_job_agent.scoring.ranker import score_job_for_student

RELEVANCE_WEIGHTS = {
    "high": 3,
    "medium": 2,
    "low": 1,
}

BENCHMARK_STUDENT = StudentProfile(
    name="MSIS Benchmark Student",
    concentration="Data Analytics and AI",
    target_roles=[
        "data analyst",
        "cybersecurity analyst",
        "technology risk",
        "product manager",
        "software engineer",
    ],
    skills=[
        "sql",
        "python",
        "dashboard",
        "security",
        "grc",
        "product",
        "api",
        "ai",
    ],
    stage="internship search",
)


@dataclass(frozen=True)
class ClassificationResult:
    """One gold posting classifier comparison."""

    posting_id: str
    title: str
    expected_role: str
    predicted_roles: list[str]
    expected_concentration: str
    predicted_concentrations: list[str]

    @property
    def role_match(self) -> bool:
        return self.expected_role in self.predicted_roles

    @property
    def concentration_match(self) -> bool:
        return self.expected_concentration in self.predicted_concentrations


@dataclass(frozen=True)
class ClassificationEvaluation:
    """Aggregate classifier benchmark metrics."""

    results: list[ClassificationResult]

    @property
    def total(self) -> int:
        return len(self.results)

    @property
    def role_accuracy(self) -> float:
        return _ratio(sum(result.role_match for result in self.results), self.total)

    @property
    def concentration_accuracy(self) -> float:
        return _ratio(
            sum(result.concentration_match for result in self.results), self.total
        )

    @property
    def exact_match_accuracy(self) -> float:
        matches = sum(
            result.role_match and result.concentration_match for result in self.results
        )
        return _ratio(matches, self.total)

    @property
    def misses(self) -> list[ClassificationResult]:
        return [
            result
            for result in self.results
            if not result.role_match or not result.concentration_match
        ]


@dataclass(frozen=True)
class RankingResult:
    """One gold posting ranking comparison."""

    posting_id: str
    title: str
    relevance: str
    score: float
    rank: int


@dataclass(frozen=True)
class RankingEvaluation:
    """Aggregate ranking benchmark metrics."""

    results: list[RankingResult]

    @property
    def total(self) -> int:
        return len(self.results)

    @property
    def pairwise_ordering_accuracy(self) -> float:
        comparisons = 0
        ordered = 0
        for left in self.results:
            for right in self.results:
                left_weight = RELEVANCE_WEIGHTS[left.relevance]
                right_weight = RELEVANCE_WEIGHTS[right.relevance]
                if left_weight <= right_weight:
                    continue
                comparisons += 1
                if left.score >= right.score:
                    ordered += 1

        return _ratio(ordered, comparisons)

    @property
    def mean_score_by_relevance(self) -> dict[str, float]:
        means: dict[str, float] = {}
        for relevance in RELEVANCE_WEIGHTS:
            scores = [
                result.score
                for result in self.results
                if result.relevance == relevance
            ]
            if scores:
                means[relevance] = sum(scores) / len(scores)
        return means

    @property
    def top_ranked(self) -> list[RankingResult]:
        return sorted(self.results, key=lambda result: result.rank)


def evaluate_classifier(postings: list[GoldJobPosting]) -> ClassificationEvaluation:
    """Compare classifier role/concentration tags against manual gold labels."""

    results = []
    for posting in postings:
        classification = classify_job(_to_unlabeled_job_posting(posting))
        labels = posting.manual_labels
        results.append(
            ClassificationResult(
                posting_id=posting.id,
                title=posting.title,
                expected_role=labels.primary_role,
                predicted_roles=classification.role_tags,
                expected_concentration=labels.concentration,
                predicted_concentrations=classification.concentration_tags,
            )
        )

    return ClassificationEvaluation(results=results)


def evaluate_ranking(
    postings: list[GoldJobPosting],
    student: StudentProfile = BENCHMARK_STUDENT,
) -> RankingEvaluation:
    """Compare ranker scores against manual relevance labels."""

    scored = [
        (
            posting,
            score_job_for_student(student, _to_unlabeled_job_posting(posting)),
        )
        for posting in postings
    ]
    ranked = sorted(scored, key=lambda item: item[1], reverse=True)

    return RankingEvaluation(
        results=[
            RankingResult(
                posting_id=posting.id,
                title=posting.title,
                relevance=posting.manual_labels.relevance,
                score=score,
                rank=index,
            )
            for index, (posting, score) in enumerate(ranked, start=1)
        ]
    )


def _to_unlabeled_job_posting(posting: GoldJobPosting) -> JobPosting:
    return JobPosting(
        source=posting.source,
        title=posting.title,
        company=posting.company,
        location=posting.location,
        description=posting.posting_summary,
        url=str(posting.source_url),
    )


def _ratio(numerator: int, denominator: int) -> float:
    if denominator == 0:
        return 0.0
    return numerator / denominator


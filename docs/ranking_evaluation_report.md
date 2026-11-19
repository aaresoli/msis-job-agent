# Ranking Evaluation Report

## Purpose

This report records the current classifier and ranking benchmark results for
the HOPE MSIS Job Agent MVP. It uses the manually labeled gold set in
`data/gold_job_postings_labeled.json` and the same classify-then-rank flow used
by the MVP pipeline.

## How To Reproduce

Run from the repository root:

```bash
python scripts/evaluate_gold_set.py
```

The automated regression tests in `tests/test_gold_evaluation.py` enforce the
minimum quality gates.

## Current Results

Last verified: June 22, 2026

| Metric | Result | Gate |
| --- | ---: | ---: |
| Gold postings evaluated | 12 | At least 10 |
| Classifier role accuracy | 100.0% | At least 80.0% |
| Classifier concentration accuracy | 100.0% | At least 80.0% |
| Exact role + concentration accuracy | 100.0% | At least 80.0% |
| Ranking pairwise relevance accuracy | 89.7% | At least 85.0% |

Mean ranking score by manual relevance label:

| Relevance label | Mean score |
| --- | ---: |
| High | 8.33 |
| Medium | 6.00 |
| Low | 5.00 |

## Interpretation

The classifier now clears the project relevance target on the current benchmark
set. The ranker orders manually high-relevance postings ahead of weaker
postings in nearly 90% of pairwise comparisons.

The low-relevance mean remains close to the medium band because the current
ranker intentionally rewards general internship and digital-transformation
signals. Future tuning should add stronger penalties or filters for postings
that are operationally adjacent but not technical enough for MSIS target roles.

## Notes

- The benchmark uses 12 real public postings with manual role, concentration,
  seniority, and relevance labels.
- Ranking evaluation classifies each posting before scoring so it reflects the
  MVP pipeline behavior.
- The benchmark is deterministic and does not call an LLM or external service.

# Kelley HOPE MSIS Job Agent

AI-powered job discovery starter repository for MSIS students and Graduate Career Services.

This project will eventually support approved job source adapters, shared ingestion and normalization, deduplication, role/concentration classification, ranking, student-facing matching, GCS trend tracking, and digest-style delivery.

## Current Status

This repository is a Sprint 3-ready local baseline. It persists pipeline
history, normalized jobs, deduped jobs, classifications, ranking scores, and
match history to local SQLite. It does not perform live job collection from
restricted or unapproved sources.

The current code provides:

- Package structure for a FastAPI-ready Python backend
- Safe source adapter interfaces and registry guardrails
- A compliant local JSON approved-source adapter for v0 ingestion demos
- A KSBIT-compatible local JSON/CSV export adapter for approved exports
- A thin-slice CLI runner for ingestion, normalization, validation,
  classification, deduplication, ranking, and JSON output
- An MVP local pipeline runner that exports ranked per-student CSV/JSON results
  and a run summary
- Local SQLite persistence with idempotent job, classification, score, and
  match-history upserts
- Normalized job/student schemas, deterministic ranking, and GCS summaries
- A realistic labelled fixture and evaluation command
- A manually labeled gold set of real job postings for classifier and ranking
  evaluation
- pytest, Ruff, Black, mypy, and GitHub Actions checks

## Compliance Notice

Do not add unauthorized scraping, login scraping, CAPTCHA bypassing, proxy rotation, or LinkedIn scraping. Every source implementation must be reviewed and approved before it is added.

LinkedIn, Handshake, employer systems, and any third-party job source must be accessed only through official, approved, and compliant methods.

## Setup

Use Python 3.11 or newer.

```bash
python -m venv .venv
# macOS/Linux:
source .venv/bin/activate
# Windows PowerShell:
# .\.venv\Scripts\Activate.ps1
python -m pip install -e ".[dev]"
```

Create a local environment file only if needed:

```bash
cp .env.example .env
```

Never commit real secrets.

## Run Tests

```bash
python -m pytest
```

## Run The V0 Pipeline

The v0 runner only reads local approved JSON exports. It does not perform live
scraping or connect to restricted job platforms.

```bash
hope-job-agent run-pipeline --source-file docs/examples/approved_jobs.sample.json
```

The default report is written to `data/output/pipeline_results.json`.

You can also run the module directly:

```bash
python -m hope_job_agent.cli run-pipeline --source-file docs/examples/approved_jobs.sample.json
```

## Run The MVP Pipeline

The MSI-21 MVP runner composes the approved local JSON adapter, normalization,
deduplication, classification, ranking, export, and summary steps.

```bash
python -m hope_job_agent.pipeline.run_mvp --source approved_json --input data/sample_jobs.json --profiles data/sample_profiles.json --output outputs/mvp_results.csv
```

It writes `outputs/mvp_results.csv` plus
`outputs/mvp_results.summary.json`, and persists the run to
`data/hope_job_agent.sqlite3` unless `DATABASE_URL` or `--database-url` points
to another SQLite database. See `docs/mvp_pipeline.md` for the input format,
output fields, flags, and current limitations.

Run the MVP pipeline with a KSBIT-compatible local export:

```bash
python -m hope_job_agent.pipeline.run_mvp --source ksbit_export --input data/sample_ksbit_jobs.json --profiles data/sample_profiles.json --output outputs/ksbit_mvp_results.csv
```

CSV exports are supported too:

```bash
python -m hope_job_agent.pipeline.run_mvp --source ksbit_export --input data/sample_ksbit_jobs.csv --profiles data/sample_profiles.json --output outputs/ksbit_mvp_results_csv.csv
```

See `docs/ksbit_export_adapter.md` for supported formats, alias mappings,
source-level filtering, and the future API integration path.

## Run Evaluation

```bash
hope-job-agent evaluate --dataset-file tests/fixtures/labelled_postings.json
```

## Gold Job Posting Dataset

The labeled benchmark set for classifier and ranking evaluation lives at
`data/gold_job_postings_labeled.json`. Each record is a real public posting with
manual labels for MSIS target role, role fit, concentration fit, seniority, and
relevance.

Use `hope_job_agent.datasets.gold_postings.load_gold_postings()` to load and
validate the records, and `GoldJobPosting.to_job_posting()` when a test or
evaluation script needs the normalized `JobPosting` model.

Run the benchmark evaluation script from the repository root:

```bash
python scripts/evaluate_gold_set.py
```

The script reports classifier role/concentration accuracy, ranking pairwise
relevance accuracy, mean ranking score by relevance label, and classifier misses
that need follow-up taxonomy or rule work.

## Developer Commands

```bash
make install
make test
make lint
python -m black --check .
python -m mypy src
```

## Team Workflow

- Create feature branches from `main`.
- Pull the latest `main` before starting work.
- Open a pull request for review before merging.
- Never push directly to `main`.
- Keep pull requests focused and small enough to review.

Suggested branch names:

- `feature/name-task`
- `fix/name-issue`
- `docs/name-topic`

Examples:

- `feature/aashish-source-interface`
- `fix/jordan-dedup-url-normalization`
- `docs/priya-compliance-notes`

## Repository Layout

- `docs/`: architecture, compliance, source approval, and handoff notes
- `data/`: checked-in local sample inputs for the MVP runner
- `src/hope_job_agent/`: application package
- `tests/`: starter pytest suite

## Sprint 3 Assumption

The project brief references all 5 concentration tracks, while the current
validated schema contains 4 tracks. Keep the 4-track schema until the advisor
confirms the official fifth track name.


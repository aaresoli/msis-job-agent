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
- A KSBIT-compatible local JSON/CSV/XLSX export adapter for approved exports
- A thin-slice CLI runner for ingestion, normalization, validation,
  classification, deduplication, ranking, and JSON output
- An MVP local pipeline runner that exports ranked per-student CSV/JSON results,
  normalized job postings, a data-quality report, a GCS trend summary, and a run
  summary, with an optional jobs-only mode when no student profiles are provided
- Classification into the five official MSIS concentration tracks
- Local SQLite persistence with idempotent job, classification, score, and
  match-history upserts
- Normalized job/student schemas, deterministic ranking, and GCS summaries
- A checked ranking-weight config at `data/ranking_weights.json`
- A realistic labelled fixture and evaluation command
- A manually labeled gold set of real job postings for classifier and ranking
  evaluation
- A taxonomy calibration harness (`evaluate-taxonomy`) reporting per-role and
  per-concentration precision/recall/F1, ready for a real labeled export
- Interpretable location matching that expands nicknames/regions
  (for example `Indy` → `Indianapolis`) without geocoding
- Configurable, documented data-quality thresholds
  (`data/data_quality_thresholds.json` + CLI overrides)
- A committed, schema-faithful synthetic 12Twenty export
  (`data/sample_12twenty_export.xlsx`) so the Excel path is tested without PII
- An enriched GCS trend contract aligned with `sql/gcs_trend_queries.sql`
- A pluggable persistence seam (`JobStore` protocol + `create_job_store`) so a
  future PostgreSQL backend is a drop-in for local SQLite
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

The v0 runner defaults to local approved JSON exports and can also read
approved KSBIT-compatible local exports. It does not perform live scraping or
connect to restricted job platforms.

```bash
hope-job-agent run-pipeline --source-file docs/examples/approved_jobs.sample.json
```

The default report is written to `data/output/pipeline_results.json`.

Select the KSBIT export adapter with `--source ksbit_export`:

```bash
hope-job-agent run-pipeline --source ksbit_export --source-file data/sample_ksbit_jobs.json --output-file outputs/ksbit_pipeline_results.json
```

When `--source-file` is omitted, `approved_json` uses `APPROVED_JOBS_PATH` and
`ksbit_export` uses `KSBIT_EXPORT_PATH`. Both default to checked-in local sample
exports for development.

You can also run the module directly:

```bash
python -m hope_job_agent.cli run-pipeline --source-file docs/examples/approved_jobs.sample.json
```

## Run The MVP Pipeline

The MVP runner composes an approved local adapter, normalization,
deduplication, classification, optional ranking, export, and summary steps.

### Jobs-only mode (no student profiles)

When `--profiles` is omitted the runner ingests, normalizes, deduplicates, and
classifies postings and writes normalized jobs, a data-quality report, and a
GCS trend summary. This is the fastest way to demo an approved 12Twenty /
KelleyLink Excel export:

```bash
python -m hope_job_agent.pipeline.run_mvp --source kelleylink_excel --input "12Twenty Data Example v1.xlsx" --output outputs/mvp_jobs.csv
```

`kelleylink_excel` is an approved alias of `ksbit_export`; both use the same
local-export adapter and accept `.xlsx`, `.csv`, and `.json`.

### Student-matching mode (with profiles)

Provide `--profiles` to also rank jobs per consenting student:

```bash
python -m hope_job_agent.pipeline.run_mvp --source approved_json --input data/sample_jobs.json --profiles data/sample_profiles.json --output outputs/mvp_results.csv
```

### Outputs

From a single `--output outputs/<name>.csv` the runner derives:

- `outputs/<name>.csv` — ranked student matches (student-matching mode) or the
  normalized jobs (jobs-only mode)
- `outputs/<name>.jobs.csv` — normalized + classified postings (student mode)
- `outputs/<name>.data_quality.json` — data-quality report for KSBIT/GCS
- `outputs/<name>.gcs_trends.json` — GCS program-level trend summary
- `outputs/<name>.summary.json` — run summary with counts and artifact paths

The `.json` output extension switches the jobs export to JSON. Runs persist to
`data/hope_job_agent.sqlite3` unless `DATABASE_URL`/`--database-url` points to
another SQLite database; pass `--skip-store` to write files without persisting,
or `--dry-run` to skip all writes. See `docs/mvp_pipeline.md` and
`docs/ksbit_export_adapter.md` for formats, alias mappings, source-level
filtering, and the future Denodo/API integration path.

Data-quality thresholds default to `data/data_quality_thresholds.json` (a short
description is under 200 chars; a posting is stale after 90 days). These are
deliberate proxies; override per run with `--dq-short-description-chars` and
`--dq-stale-days`, and the thresholds used are recorded in the report.

Persistence goes through the `JobStore` protocol via `create_job_store`. Empty
and `sqlite://` URLs use the local SQLite backend. A `postgresql://` URL is the
intended drop-in point for a shared/production backend and currently raises a
clear "not implemented yet" error rather than silently doing nothing.

### Exercising the synthetic 12Twenty Excel export

`data/sample_12twenty_export.xlsx` mirrors the real 12Twenty dry-run schema
(JSON location cells, status values, work-authorization strings, and the
sensitive analytics columns the adapter must drop) with entirely fabricated
data. Regenerate it with `python scripts/generate_sample_12twenty_xlsx.py`.

```bash
python -m hope_job_agent.pipeline.run_mvp --source kelleylink_excel --input data/sample_12twenty_export.xlsx --output outputs/twelve_twenty_jobs.csv
```

Additional examples:

```bash
# KSBIT-compatible local JSON/CSV, with student profiles
python -m hope_job_agent.pipeline.run_mvp --source ksbit_export --input data/sample_ksbit_jobs.json --profiles data/sample_profiles.json --output outputs/ksbit_mvp_results.csv
python -m hope_job_agent.pipeline.run_mvp --source ksbit_export --input data/sample_ksbit_jobs.csv --profiles data/sample_profiles.json --output outputs/ksbit_mvp_results_csv.csv
```

## Run Evaluation

```bash
hope-job-agent evaluate --dataset-file tests/fixtures/labelled_postings.json
```

### Taxonomy calibration harness

`evaluate-taxonomy` reports per-role and per-concentration precision, recall,
and F1 against the labeled datasets. Run it after a real labeled KelleyLink/KSBIT
export becomes available to tune keyword lists with evidence rather than
guesswork.

```bash
hope-job-agent evaluate-taxonomy --dataset all      # gold + synthetic fixture
hope-job-agent evaluate-taxonomy --dataset gold     # real gold postings only
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

The current benchmark summary is captured in
`docs/ranking_evaluation_report.md`.

## Ranking Configuration

The default deterministic ranking rubric is mirrored in
`data/ranking_weights.json`. Use
`hope_job_agent.scoring.ranker.load_ranking_weights()` to validate and load a
different weight file for experiments without changing the hard-coded safe
defaults used by the MVP runner.

## Developer Commands

```bash
make install
make test
make lint
make smoke
make quality
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

## MSIS Concentration Tracks

Classification uses the five official Kelley MSIS concentrations (defined in
`src/hope_job_agent/classification/taxonomy.py`):

- Data Analytics and AI (DA & AI)
- Cybersecurity and Risk Analytics (CRA)
- Digital Enterprise Systems and AI (DES & AI)
- Digital Platforms and Security (DPS)
- IS Research (ISR)

Legacy track names from earlier sprints are mapped onto these five via
`LEGACY_CONCENTRATION_ALIASES`, so older exports and profiles still classify
correctly without a data migration.

## Adding A New Source Adapter

1. Implement `BaseJobSource` in `src/hope_job_agent/sources/` (see
   `sources/ksbit_export.py`). Return normalized `JobPosting` objects; do not
   mix LLM inference into raw ingestion.
2. Register it in `sources/registry.py` with a `SourceMetadata` entry and the
   correct `SourceStatus` (only `APPROVED` sources run).
3. If it loads from a local file path, wire it into `create_source_adapter`.
4. Add tests and update `docs/source_approval_checklist.md`.

## Staged Roadmap

- Phase 1 (current): stabilize the local MVP — Excel/CSV/JSON ingest, five-track
  classification, data-quality report, GCS trends, and student matching.
- Phase 2: `ksbit_denodo` API adapter behind the same `BaseJobSource` contract
  and registry approval once the Denodo view schema is confirmed.
- Phase 3: durable database persistence beyond local SQLite. The `JobStore`
  protocol and `create_job_store` factory are already in place so a
  `PostgresJobStore` is a drop-in; only the concrete backend remains.
- Phase 4: optional LLM enrichment / embeddings as pluggable services.
- Phase 5: scheduled/automated runs.
- Phase 6: student- and GCS-facing delivery layer.

# Kelley HOPE MSIS Job Agent

Local-first career intelligence for Kelley MSIS students and Graduate Career Services.

The repository now contains the production-shaped campus pilot: approved-source
ingestion, hybrid matching, advisory career coaching, application tracking,
privacy controls, GCS aggregate analytics, automation, and a mobile-first web app.

## Current Status

The platform is ready for local deployment and external endpoint mapping. Local
Ollama inference is wired end to end and enabled by pointing `OLLAMA_BASE_URL`
and `OLLAMA_CHAT_MODEL` at a running server — see
[the DGX Spark runbook](docs/dgx_spark_deployment.md) for the model choices and
why they are MoE. Live Denodo and Apify LinkedIn calls remain disabled until
their credentials, payload fixtures, and approvals are supplied. The existing
SQLite CLI remains available for offline demos; the web platform uses
PostgreSQL and pgvector.

The current code provides:

- FastAPI `/api/v1` student/GCS API with invite-only magic links, CSRF,
  role checks, sharing grants, audit records, export, and deletion requests
- PostgreSQL/pgvector system of record plus private MinIO documents and Redis
  queues, with 768-dimensional `embeddinggemma` metadata
- Four LangGraph workflows for enrichment, hybrid matching, advisory coaching,
  and cited Market Pulse signals, with optional PostgreSQL checkpointing
- Provider-neutral local inference with an Ollama implementation and graceful
  deterministic/vector fallback, tuned for concurrent decode on the Spark
  (parallel slots, KV quantization, per-workload context and reasoning effort)
- Per-call inference telemetry — prompt/generated tokens, decode seconds, and
  model-load seconds — exported as Prometheus counters and structured logs, so
  throughput and model eviction are observable rather than inferred
- Separate interactive and batch Celery queues
- A Celery Beat scheduler whose schedule is declared in Python
  (`src/hope_job_agent/workers/schedules.py`), on by default with the platform
- A transactional-outbox relay that delivers student digest email, plus
  nightly verified backups, Prometheus alert rules, and Alertmanager
- Editorial Next.js PWA for Today, Explore, job dossiers, applications, coach,
  privacy/profile, notifications, Market Pulse, and aggregate GCS views
- Docker Compose profiles for the platform, local AI, observability, and a
  Caddy/Cloudflare edge, plus a systemd unit so the stack survives a reboot
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

Do not enable unauthorized scraping, login scraping, CAPTCHA bypassing, or proxy
rotation. Every source implementation must be reviewed and approved before it
is enabled. The Apify LinkedIn contract additionally requires a recorded
institutional/legal approval ID.

LinkedIn, Handshake, employer systems, and any third-party job source must be accessed only through official, approved, and compliant methods.

## Setup

Requires Python 3.14 and [uv](https://docs.astral.sh/uv/). Dependencies are
resolved from the committed `uv.lock`, so every environment installs the same
set.

```bash
uv sync
```

That creates `.venv` and installs the project with its development tools. Run
commands through `uv run` (for example `uv run pytest`) so they use it without
a manual activation step.

Create a local environment file only if needed:

```bash
cp .env.example .env
```

Never commit real secrets.

## Run the campus platform

The default platform profile starts PostgreSQL, Redis, MinIO, migrations,
LangGraph checkpoint initialization, FastAPI, the four Celery workers, the
scheduler, and Next.js. Scheduled work is on from the moment the platform is
up -- source refreshes, digests, backups, reconciliation, and retention all run
without an extra profile or a manual import step:

```bash
cp .env.example .env
# Replace every development-only secret before any shared deployment.
docker compose --profile platform up --build
```

Optional private profiles:

```bash
docker compose --profile platform --profile ai up -d
docker compose --profile platform --profile observability up -d
```

Only add `--profile edge` after configuring the Caddy host and a Cloudflare
tunnel token. Phoenix, Grafana, Prometheus, Alertmanager, MinIO, PostgreSQL,
Redis, and Ollama bind privately or to loopback and must not be added to the
public tunnel.

The schedule lives in `src/hope_job_agent/workers/schedules.py` and is covered
by `tests/test_schedules.py`. To keep the platform running across reboots,
install the systemd unit in `infra/systemd/` -- see the
[DGX Spark runbook](docs/dgx_spark_deployment.md).

Invite a launch user through the internal API (include unique idempotency and
request IDs in operational clients), then sign in at `http://localhost:3000`.
SMTP is required to deliver magic links outside a controlled local test.

Useful verification commands:

```bash
pytest
ruff check src tests scripts && black --check src tests scripts && mypy src
docker run --rm -v "$PWD/infra/prometheus:/p" --entrypoint promtool \
  prom/prometheus:v3.7.3 check rules /p/rules/hope.yml
cd web && npm ci && npm run lint && npm run typecheck && npm test && npm run build
```

## Database Setup (PostgreSQL + pgvector)

Local PostgreSQL uses the pgvector-enabled service in `docker-compose.yml`.

```bash
docker compose up -d postgres
cp .env.example .env
alembic upgrade head
```

Set persistence explicitly when running the MVP pipeline:

```bash
# Dry-run without persisting
python -m hope_job_agent.pipeline.run_mvp \
  --source kelleylink_excel \
  --input data/sample_12twenty_export.xlsx \
  --output outputs/mvp_jobs.csv \
  --dry-run

# Persist to PostgreSQL
python -m hope_job_agent.pipeline.run_mvp \
  --source kelleylink_excel \
  --input data/sample_12twenty_export.xlsx \
  --output outputs/mvp_jobs.csv \
  --storage postgres

# Company careers into PostgreSQL
python -m hope_job_agent.pipeline.run_mvp \
  --source company_careers \
  --output outputs/company_careers/results.json \
  --storage postgres \
  --limit 200

# In-memory persistence for tests/demos (no database)
python -m hope_job_agent.pipeline.run_mvp \
  --source approved_json \
  --input data/sample_jobs.json \
  --output outputs/jobs.csv \
  --storage memory
```

Import an existing local export into PostgreSQL:

```bash
python -m hope_job_agent.db.import_existing_jobs \
  --input data/sample_ksbit_jobs.json \
  --source ksbit_export
```

Useful commands:

```bash
alembic current
alembic history
alembic downgrade -1
pytest -m unit
pytest -m postgres   # requires docker postgres + alembic upgrade head
```

Reset the local database:

```bash
docker compose down -v
docker compose up -d postgres
alembic upgrade head
```

Environment variables (see `.env.example`):

- `DATABASE_URL` — preferred; example `postgresql+psycopg://hope_user:hope_password@localhost:5432/hope_jobs`
- `POSTGRES_HOST`, `POSTGRES_PORT`, `POSTGRES_DB`, `POSTGRES_USER`, `POSTGRES_PASSWORD` — used when `DATABASE_URL` is empty
- `EMBEDDING_DIMENSION` — pgvector column size (default `768`, matching `embeddinggemma`); changing it requires a new Alembic migration

### How sources connect to PostgreSQL

All approved source adapters still return normalized `JobPosting` objects. The MVP
runner normalizes, validates, deduplicates, and classifies jobs, then persists
through the `JobStore` protocol:

- **KelleyLink/KSBIT** (`kelleylink_excel`, `ksbit_export`) — local export adapters; persisted via `JobPostingRepository.upsert_many` and audited in `source_runs`.
- **Company careers** (`company_careers`) — ATS-backed public boards; same repository path with company rows in `companies`.
- **Denodo (future)** — planned `ksbit_denodo` adapter behind `BaseJobSource`; will use the same repository layer once the view schema is approved.

pgvector embeddings are optional during ingestion. Jobs persist without
embeddings; `job_embeddings` is populated by a future embedding step keyed by
text hash.

Inspect recent ingestion health:

```sql
SELECT source_name, run_status, started_at, jobs_inserted, jobs_updated, errors_count
FROM source_runs
ORDER BY started_at DESC
LIMIT 20;
```

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
and `sqlite://` URLs use the local SQLite backend. Pass `--storage postgres`
(or set `DATABASE_URL` to a `postgresql+psycopg://` URL) for shared/production
PostgreSQL persistence with pgvector-ready schema.

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

### Company Careers source (public ATS boards)

`company_careers` fetches MSIS-relevant postings directly from **public**
employer career pages and public ATS APIs (Greenhouse, Lever, Ashby,
SmartRecruiters, Workday), filters them for MSIS relevance, and runs them
through the same pipeline. It is config-driven (`config/company_careers.yml`)
and runs **independently of Denodo**. Full guide: `docs/company_careers.md`.

```bash
# company_careers only (jobs-only, dry-run; no files written)
python -m hope_job_agent.pipeline.run_mvp --source company_careers --limit 200 --dry-run

# company_careers only, writing outputs
python -m hope_job_agent.pipeline.run_mvp --source company_careers \
  --company-config config/company_careers.yml \
  --output outputs/company_careers/results.json --skip-store

# all enabled sources: company_careers + a local export
python -m hope_job_agent.pipeline.run_mvp --source all \
  --local-source kelleylink_excel --input data/sample_ksbit_jobs.json \
  --output outputs/all/results.json --skip-store
```

The run summary and CLI print a per-company health report
(fetched/kept/skipped/errors). Compliance: public pages only; no
LinkedIn/Handshake; no login/CAPTCHA/proxy circumvention; robots.txt respected;
rate limited; a source that blocks the crawler is disabled automatically.

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

Legacy/shorthand track names (including short codes such as `CRA`/`DPS` and
values like `ERP`, `SAP`, `Technology Architecture`, `Business Intelligence and
Analytics`) are normalized onto these five by `normalize_concentration` /
`LEGACY_CONCENTRATION_ALIASES`, so older exports and profiles still classify
correctly without a data migration. Final classifier output always uses the
official names. The full alias map is in `docs/company_careers.md`.

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
- Phase 3: durable PostgreSQL persistence with pgvector, Alembic migrations, and
  repository abstractions (`JobPostingRepository`, `SourceRunRepository`, etc.).
  SQLite and in-memory backends remain for local development and tests.
- Phase 4: optional LLM enrichment / embeddings as pluggable services.
- Phase 5: scheduled/automated runs.
- Phase 6: student- and GCS-facing delivery layer.

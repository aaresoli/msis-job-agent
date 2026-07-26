# Architecture

This repository is organized around a modular job discovery pipeline, deployed
as a small platform around it. The pipeline sections below describe the core
domain logic; the platform sections describe what runs it in production.

## Platform

- **API**: FastAPI (`hope_job_agent.main`), serving the student-facing routes
  under `/api/v1` and operator routes under `/internal/v1`.
- **Web**: Next.js app in `web/`, typed against `web/openapi.json` — both the
  schema and the generated client types are regenerated and diff-checked in CI.
- **Storage**: PostgreSQL with pgvector for job embeddings (HNSW, cosine).
  SQLite remains supported for the standalone pipeline CLI and tests.
- **Background work**: Celery over Redis, split across four queues —
  `interactive`, `batch`, `ingest`, `ops` — with one worker container each.
  `hope_job_agent.workers.schedules` holds the beat schedule; a single `beat`
  container runs it. See `docs/dgx_spark_deployment.md`.
- **Local inference**: Ollama, behind the `ModelProvider` protocol in
  `hope_job_agent.ai.provider`. Models are split by workload (a larger batch
  model, a smaller interactive one for the streaming coach). No hosted model
  provider is used, and an unreachable model degrades to `review`/`degraded`
  rather than failing the request.
- **Structured output**: every extraction path runs a
  generate → validate → retry loop against a Pydantic schema
  (`hope_job_agent.ai.schemas`), with evidence quotes checked verbatim against
  the source text.
- **Delivery**: a transactional outbox relayed on a schedule, so a notification
  is never sent for a transaction that rolled back.

## Implemented Local Baseline

- Source adapters: approved local JSON, KelleyLink/KSBIT local export, an
  employer-careers fixture, and the `company_careers` source that fetches from
  public ATS job boards (Greenhouse, Lever, Ashby, SmartRecruiters, Workday).
  See `docs/company_careers.md`.
- Source registry: blocks restricted/manual-reference sources at runtime.
- Ingestion pipeline: common entry point for loading records from approved sources.
- Normalization: converts source-specific records into shared `JobPosting` objects.
- Validation: rejects incomplete or unsafe records before ranking or delivery.
- Deduplication: removes canonical URL duplicates and exact content duplicates.
- Classification: maps jobs to MSIS role and concentration categories.
- Scoring: ranks jobs against student profiles with explainable reasons.
- Agents: student matching and GCS trend summaries.
- Persistence: local SQLite stores pipeline runs, normalized and deduped jobs,
  classification results, ranking scores, and match history with idempotent
  upserts.
- Delivery: local JSON reports and email-digest text formatting.
- Evaluation: realistic labelled fixture with classification and ranking metrics.

## MSIS Concentrations

The project uses the five official Kelley MSIS concentration names everywhere:
Data Analytics and AI; Cybersecurity and Risk Analytics; Digital Enterprise
Systems and AI; Digital Platforms and Security; IS Research. Legacy/shorthand
names are normalized forward by
`hope_job_agent.classification.taxonomy.normalize_concentration`; final outputs
never use the outdated names. See `docs/company_careers.md` for the alias map.

## Current Scope Limits

Live collection is limited to the `company_careers` source, which uses public
ATS/career-page endpoints only (rate limited, robots-aware, clear User-Agent),
and the Apify LinkedIn posts source where a token is configured. Handshake and
the KSBIT/Denodo integration remain unapproved: their adapters return
`disabled` at runtime rather than fetching, and `sql/gcs_trend_queries.sql`
holds query drafts against a schema that has not been agreed.

The platform runs on a single host. There is no horizontal scaling story, no
multi-tenancy, and exactly one `beat` container by construction — a second one
would fire every scheduled task twice.


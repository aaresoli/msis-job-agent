# Architecture

This repository is organized around a modular job discovery pipeline.

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

No queueing or LinkedIn/Handshake collection is included. Live collection is
limited to the `company_careers` source, which uses public ATS/career-page
endpoints only (rate limited, robots-aware, clear User-Agent). Persistence is
local SQLite only.


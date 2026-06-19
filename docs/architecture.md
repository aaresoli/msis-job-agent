# Architecture

This repository is organized around a modular job discovery pipeline.

## Implemented Local Baseline

- Source adapters: approved local JSON and employer-careers fixture adapters.
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

## Current Scope Limits

No production data collection, queueing, live ATS/API calls, or
LinkedIn/Handshake collection are included. Persistence is local SQLite only.
The current 4-track concentration schema remains in place until the advisor
confirms the project brief's fifth track.


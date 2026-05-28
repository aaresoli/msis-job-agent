# Architecture

This repository is organized around a modular job discovery pipeline.

## Planned Components

- Source adapters: approved integrations for employer career pages, Handshake/API access if approved, and compliant reference sources.
- Ingestion pipeline: common entry point for loading raw job postings from approved sources.
- Normalization: converts source-specific records into shared `JobPosting` objects.
- Validation: rejects incomplete or unsafe records before ranking or delivery.
- Deduplication: removes repeated postings across sources.
- Classification: maps jobs to MSIS role and concentration categories.
- Scoring: ranks jobs against student profiles.
- Agents: student matching and GCS trend summaries.
- Delivery: email or digest-style output.

## Current Scope

Only starter interfaces and simple local functions are implemented. No production data collection, database writes, queueing, or external API calls are included yet.


# Kelley HOPE MSIS Job Agent

AI-powered job discovery starter repository for MSIS students and Graduate Career Services.

This project will eventually support approved job source adapters, shared ingestion and normalization, deduplication, role/concentration classification, ranking, student-facing matching, GCS trend tracking, and digest-style delivery.

## Current Status

This repository is a base scaffold only. It does not implement the full product yet, does not connect to a database, and does not perform live job collection from restricted or unapproved sources.

The current code provides:

- Package structure for a FastAPI-ready Python backend
- Safe source adapter interfaces and placeholder stubs
- Simple model, normalization, deduplication, ranking, and digest helpers
- Documentation placeholders for architecture, compliance, and handoff
- pytest-based starter tests

## Compliance Notice

Do not add unauthorized scraping, login scraping, CAPTCHA bypassing, proxy rotation, or LinkedIn scraping. Every source implementation must be reviewed and approved before it is added.

LinkedIn, Handshake, employer systems, and any third-party job source must be accessed only through official, approved, and compliant methods.

## Setup

Use Python 3.11 or newer.

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements-dev.txt
```

Create a local environment file only if needed:

```bash
cp .env.example .env
```

Never commit real secrets.

## Run Tests

```bash
pytest
```

## Developer Commands

```bash
make install
make test
make lint
make format
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
- `src/hope_job_agent/`: application package
- `tests/`: starter pytest suite


---
name: repo-architecture
description: Explain the repository architecture for Kelley HOPE MSIS Job Agent project
source: auto-skill
extracted_at: '2026-06-30T15:29:10.414Z'
---

# Repository Architecture Explanation

## High-Level System Flow

```
Jobs Source → Ingestion → Normalization → Validation → Classification 
  → Deduplication → Ranking → Delivery → Persistence
```

## Core Components

### 1. Data Models (`src/hope_job_agent/models/`)
- **`job.py`**: `JobPosting` - normalized job record with title, company, location, description, URL, roles/concentrations tags, confidence scores, OPT/CPT flag
- **`student.py`**: `StudentProfile` - student data (skills, target roles, concentration, academic stage, work auth)
- **`match.py`**: `JobMatch` - ranking result with score, explanation reasons, and metadata

### 2. Source Adapters (`src/hope_job_agent/sources/`)
| Adapter | Status | Description |
|---------|--------|-------------|
| `approved_json.py` | ✅ Active | Local JSON export (v0 approved source) |
| `ksbit_export.py` | ✅ Active | KSBIT-compatible CSV/JSON export |
| `handshake.py` | ⚠️Reference | Handshake integration (not implemented - blocked for compliance) |
| `linkedin_reference.py` | ⚠️Reference | LinkedIn reference (not implemented - restricted) |
| `employer_careers.py` | ✅ Active | Employer careers page adapter |

**Registry Guard**: `registry.py` blocks unapproved sources at runtime

### 3. Pipeline Stages (`src/hope_job_agent/pipeline/`)
- **`ingest.py`**: Load raw jobs from source
- **`normalize.py`**: Convert source-specific formats → `JobPosting`
- **`validate.py`**: Reject incomplete records (missing title/company/location/description/url)
- **`deduplicate.py`**: Remove canonical URL duplicates + exact content duplicates
- **`runner.py`**: Thin-slice pipeline (ingest→normalize→validate→classify→dedupe→rank)
- **`run_mvp.py`**: Full MVP pipeline with CSV/JSON export + SQLite persistence

### 4. Classification (`src/hope_job_agent/classification/`)
- **`classifier.py`**: Rule-based keyword matching for:
  - MSIS **target roles** (e.g., "Data Analyst", "Business Intelligence Engineer")
  - **concentration tracks** (e.g., "Data Analytics and AI")
- Outputs role/concentration tags with confidence scores
- Maps roles → concentrations automatically

### 5. Scoring & Ranking (`src/hope_job_agent/scoring/`)
- **`ranker.py`**: Deterministic scoring rubric:
  - Skill match (**+2.0**)
  - Target role match (**+3.0**)
  - Concentration match (**+2.0**)
  - OPT/CPT compatibility (**+1.0**)
  - Seniority match (**+1.0**) / mismatch (**-1.0**)
- Produces explainable scores with reasons list

### 6. Agents (`src/hope_job_agent/agents/`)
- **`student_agent.py`**: Student matching logic
- **`gcs_agent.py`**: GCS (Graduate Career Services) trend summaries

### 7. Persistence (`src/hope_job_agent/storage/`)
- **`sqlite_store.py`**: SQLite store for:
  - Pipeline runs
  - Normalized/deduped jobs
  - Classification results
  - Ranking scores
  - Match history
- Idempotent upserts (prevents duplicates)

### 8. Delivery (`src/hope_job_agent/delivery/`)
- Local JSON export (pipeline runner)
- CSV export (MVP runner with 14 columns)
- Summary JSON with run metadata

### 9. Evaluation (`src/hope_job_agent/evaluation/`)
- **`evaluate.py`**: Classifier/ranking metrics
- **`gold_set.py`**: Benchmarks on labeled dataset
- **`scripts/evaluate_gold_set.py`**: Real evaluation script

## Key Configuration

**`data/ranking_weights.json`**: Configurable scoring weights (currently 6 rubric items)

**`.env.example`**: Environment variables for database URL and environment mode

**`src/hope_job_agent/config.py`**: Settings management with Pydantic

## Entry Points

| Command | Purpose |
|---------|---------|
| `hope-job-agent run-pipeline --source-file <file>` | Thin-slice pipeline (JSON output) |
| `python -m hope_job_agent.pipeline.run_mvp ...` | Full MVP pipeline (CSV + JSON summary) |
| `hope-job-agent evaluate --dataset-file <file>` | Classifier/ranking metrics |

## Compliance Guardrails

- **❌** No unauthorized scraping
- **❌** No LinkedIn/Handshake login automation
- **❌** No CAPTCHA bypass/proxy rotation
- **✅** All sources must be approved via `sources/registry.py`

## Tech Stack
- **Backend**: FastAPI + Uvicorn
- **Models**: Pydantic v2
- **Persistence**: SQLite (local)
- **Testing**: pytest + Ruff + Black + mypy
- **Container**: Docker (Python 3.11)

---

## Usage Examples

### Run the thin-slice pipeline:
```bash
hope-job-agent run-pipeline --source-file docs/examples/approved_jobs.sample.json
```

### Run the MVP pipeline:
```bash
python -m hope_job_agent.pipeline.run_mvp \
  --source approved_json \
  --input data/sample_jobs.json \
  --profiles data/sample_profiles.json \
  --output outputs/mvp_results.csv
```

### Evaluate against gold dataset:
```bash
hope-job-agent evaluate --dataset-file tests/fixtures/labelled_postings.json
python scripts/evaluate_gold_set.py
```
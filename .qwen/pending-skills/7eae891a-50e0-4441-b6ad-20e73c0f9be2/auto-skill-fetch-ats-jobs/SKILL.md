---
name: fetch-ats-jobs
description: Fetch MSIS-relevant jobs from ATS sources using the company_careers pipeline
source: auto-skill
extracted_at: '2026-07-08T20:45:47.672Z'
---

# How to Fetch Jobs from ATS Sources

## Overview

The company_careers source fetches jobs from 131+ employer career pages using public ATS APIs (Greenhouse, Lever, Workday, SmartRecruiters, Oracle Cloud, Ashby). Jobs are scored for MSIS relevance and saved to JSON.

## Prerequisites

1. **Environment setup** - Copy `.env.example` and configure:
   ```bash
   cp .env.example .env
   ```

2. **Dependencies installed**:
   ```bash
   pip install -e .
   ```

3. **Config file exists**: `config/company_careers.yml` with enabled employers

## Running the Fetch

### Basic Fetch (All Enabled Companies)
```bash
python fetch_all_jobs.py
```

**Output**:
- File: `data/output/company_careers_fetch.json`
- Contains: Summary + jobs with relevance scores >= 3

**What to expect**:
- Processes ~131 enabled companies with 1.0s interval between requests
- May take 5+ minutes due to rate limiting
- Output shows per-company stats and failures

### Key Fetch Options

The fetch is controlled by `config/company_careers.yml`:

| Setting | Description |
|---------|-------------|
| `enabled: true/false` | Toggle individual company fetching |
| `priority <N>` | Lower priority = fetched first |
| `max_total_jobs_per_run` | Hard cap on jobs per run (default: 8000) |
| `relevance_threshold` | Minimum relevance score to keep (default: 3) |

### Troubleshooting

**Slow fetch?**
- Rate limiting is intentional (polite scraping)
- Reduce companies by disabling entries in config
- Lower `max_jobs_per_company` if a company has many pages

**Failed companies show error?**
- Common: `robots_disallowed` - robots.txt blocks the API endpoint
- Common: `403 blocked` - API returns 403 (check compliance logs)
- Some ATS (Deloitte, McKinsey, etc.) have custom portals - marked `unsupported`

**Output file not updating?**
- Script writes output only on successful completion
- If interrupted, partial results are not saved

## Understanding the Output JSON

```json
{
  "fetched_at": "2026-07-08T...",
  "summary": {
    "raw_count": 2442,
    "kept_count": 980,
    "duplicate_count": 0,
    "companies_total": 131,
    "per_company": [
      {"company_name": "Databricks", "provider": "greenhouse", 
       "fetched": 200, "kept": 123}
    ]
  },
  "jobs": [
    {
      "title": "Data Analyst",
      "company": "Stripe",
      "location": "Remote",
      "url": "https://stripe.com/jobs/...",
      "relevance_score": 6.0,
      "matched_keywords": ["data analyst", "sql"],
      "concentration_tags": ["Data Analytics and AI"]
    }
  ]
}
```

## Filtering to Specific Employers

To fetch only high-priority MSIS employers (e.g., NVIDIA, Intel):

1. Edit `config/company_careers.yml`
2. Set `enabled: true` for desired companies
3. Set `enabled: false` for others (or delete entries)

Example NVIDIA config:
```yaml
- company_name: "NVIDIA"
  ats_provider: workday
  host: "nvidia.wd5.myworkdayjobs.com"
  tenant: nvidia
  site: NVIDIAExternalCareerSite
  enabled: true
  priority: 26
```

## Integration with Other Sources

Jobs from `company_careers` can be combined with:
- KSBIT export (`scripts/kgsbit_export.py`)
- Approved JSON file (configured in `.env`)
- Handshake reference (not implemented - compliance blocked)

See `pipeline/run_mvp.py` for full integration flow.

---

## Typical Workflow

1. Run fetch: `python fetch_all_jobs.py`
2. Verify output: Check `data/output/company_careers_fetch.json`
3. Review summary: 980 MSIS-relevant jobs from ~20 companies processed
4. Continue pipeline: Jobs ready for student matching, ranking, CSV export

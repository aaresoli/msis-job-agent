# KSBIT Export Adapter

The `ksbit_export` source adapter reads approved local KSBIT-compatible job
exports and converts them into the shared `JobPosting` model used by ingestion,
normalization, deduplication, classification, ranking, and MVP export.

This is a local-export adapter only. It does not scrape pages, automate
browsers, log in to KSBIT, bypass CAPTCHA, use proxies, or require credentials.

## Example Usage

Run the MVP pipeline with the sample JSON export:

```bash
python -m hope_job_agent.pipeline.run_mvp --source ksbit_export --input data/sample_ksbit_jobs.json --profiles data/sample_profiles.json --output outputs/ksbit_mvp_results.csv
```

Run the same path with CSV:

```bash
python -m hope_job_agent.pipeline.run_mvp --source ksbit_export --input data/sample_ksbit_jobs.csv --profiles data/sample_profiles.json --output outputs/ksbit_mvp_results_csv.csv
```

Optional source-level incremental flags:

```bash
python -m hope_job_agent.pipeline.run_mvp --source ksbit_export --input data/sample_ksbit_jobs.json --profiles data/sample_profiles.json --output outputs/ksbit_recent.csv --source-since-date 2026-06-01 --source-limit 5
```

`--limit` still means ranked matches per student profile. Use
`--source-limit` for KSBIT source records.

## Supported Formats

JSON can be a bare list:

```json
[
  {
    "source_job_id": "ksbit-001",
    "title": "Business Analyst Intern",
    "company": "Example Analytics",
    "description": "Use SQL to analyze business data.",
    "apply_url": "https://example.com/jobs/ksbit-001"
  }
]
```

JSON can also be wrapped in one of these array keys:

- `jobs`
- `data`
- `results`
- `postings`
- `job_postings`

CSV files are read with `csv.DictReader`, so the first row must contain headers.

## Required Fields

Each record must provide these fields after alias mapping:

- `title`
- `company`
- `description`
- `apply_url`

`location` is optional at the KSBIT export boundary. Missing locations are set
to `Not specified` so the existing downstream `JobPosting` model can continue
to validate.

If `source_job_id` is missing, the adapter generates a stable fallback ID from
company, title, location, and apply URL.

## Alias Mapping

| Normalized field | Accepted aliases |
| --- | --- |
| `source_job_id` | `source_job_id`, `job_id`, `id`, `posting_id`, `requisition_id`, `req_id` |
| `title` | `title`, `job_title`, `position_title`, `role`, `name` |
| `company` | `company`, `employer`, `employer_name`, `organization`, `company_name` |
| `location` | `location`, `job_location`, `city`, `work_location`, `office_location` |
| `description` | `description`, `job_description`, `full_description`, `summary` |
| `apply_url` | `apply_url`, `post_url`, `job_url`, `url`, `application_url`, `apply_link` |
| `posted_date` | `posted_date`, `date_posted`, `created_at`, `published_at` |
| `employment_type` | `employment_type`, `job_type`, `position_type`, `work_type` |
| `seniority_level` | `seniority_level`, `seniority`, `experience_level`, `level` |

The adapter also passes through optional `concentration_tags`, `role_tags`, and
`opt_cpt_flag` when present.

## Counts And Warnings

`fetch_jobs_with_warnings()` reports:

- `raw_count`
- `loaded_count`
- `skipped_count`
- `returned_count`
- `warnings`

Invalid individual rows are skipped with warnings. Empty files, unsupported
extensions, malformed JSON, and exports with no valid jobs fail clearly.

When `since_date` is used, records with missing or unparseable `posted_date`
are included and warned about. `limit` is applied after `since_date` filtering.

## Future KSBIT API Path

A future API-backed source should preserve the same `BaseJobSource` contract and
return the same `JobPosting` fields. The API client can replace the local file
loader internally while keeping downstream pipeline logic unchanged.

Before adding a live integration, document approval in the source registry,
review access terms, and avoid credentials or session behavior in committed
code.

# KSBIT Export Adapter

The `ksbit_export` source adapter reads approved local KSBIT-compatible job
exports, including the 12Twenty/KelleyLink Excel sample export, and converts
them into the shared `JobPosting` model used by ingestion, normalization,
deduplication, classification, ranking, and MVP export.

This is a local-export adapter only. It does not scrape pages, automate
browsers, log in to KSBIT, bypass CAPTCHA, use proxies, or require credentials.

## Adapter Name And Alias

The adapter is registered as `ksbit_export`. `kelleylink_excel` is an approved
alias that constructs the identical adapter; use whichever name reads best for a
given demo. Both accept `.json`, `.csv`, and `.xlsx`.

The MVP runner supports a jobs-only mode: omit `--profiles` to emit the
normalized jobs, a data-quality report, and a GCS trend summary without student
ranking. For example:

```bash
python -m hope_job_agent.pipeline.run_mvp --source kelleylink_excel --input "12Twenty Data Example v1.xlsx" --output outputs/mvp_jobs.csv
```

## Example Usage

The top-level CLI can run the adapter directly:

```bash
hope-job-agent run-pipeline --source ksbit_export --source-file data/sample_ksbit_jobs.json --output-file outputs/ksbit_pipeline_results.json
```

If `--source-file` is omitted, the top-level CLI uses `KSBIT_EXPORT_PATH`.
The default development value is `data/sample_ksbit_jobs.json`.

Run the MVP pipeline with the sample JSON export:

```bash
python -m hope_job_agent.pipeline.run_mvp --source ksbit_export --input data/sample_ksbit_jobs.json --profiles data/sample_profiles.json --output outputs/ksbit_mvp_results.csv
```

Run the same path with CSV:

```bash
python -m hope_job_agent.pipeline.run_mvp --source ksbit_export --input data/sample_ksbit_jobs.csv --profiles data/sample_profiles.json --output outputs/ksbit_mvp_results_csv.csv
```

Run the same path with an approved 12Twenty/KelleyLink `.xlsx` export:

```bash
python -m hope_job_agent.pipeline.run_mvp --source ksbit_export --input "/path/to/12Twenty Data Example v1.xlsx" --profiles data/sample_profiles.json --output outputs/ksbit_mvp_results_xlsx.csv
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

Excel files must use `.xlsx`. The adapter reads the first worksheet and treats
the first non-empty row as headers. The observed 12Twenty/KelleyLink sample
headers include `Job Posting ID`, `Job Title`, `Company Name`, `Status`,
`Posted Date`, `Job Description`, `Application URL`, `Location`,
`Location Type`, `Job Type`, `Employment Type`,
`Work Authorization Requirement`, and `Other Work Authorization`.

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

For 12Twenty Excel exports, rows without a stable `Application URL` are skipped.
Email-only and KelleyLink-site-only application rows are out of scope until an
approved stable apply URL is available.

## Alias Mapping

| Normalized field | Accepted aliases |
| --- | --- |
| `source_job_id` | `source_job_id`, `job_posting_id`, `job_id`, `id`, `posting_id`, `requisition_id`, `req_id` |
| `title` | `title`, `job_title`, `position_title`, `role`, `name` |
| `company` | `company`, `employer`, `employer_name`, `organization`, `company_name` |
| `location` | `location`, `job_location`, `city`, `work_location`, `office_location` |
| `description` | `description`, `job_description`, `full_description`, `summary` |
| `apply_url` | `apply_url`, `post_url`, `job_url`, `url`, `application_url`, `apply_link` |
| `posted_date` | `posted_date`, `date_posted`, `created_at`, `published_at` |
| `employment_type` | `employment_type`, `job_type`, `position_type`, `work_type` |
| `seniority_level` | `seniority_level`, `seniority`, `experience_level`, `level` |

The adapter also passes through optional `concentration_tags`, `role_tags`, and
`opt_cpt_flag` when present. For 12Twenty Excel exports, `Location` JSON such as
`{"CityName":"Bloomington - IN"}` is normalized to `Bloomington, IN`, and
`Remote/Telecommute` location types become `Remote`.

## 12Twenty Status And Work Authorization

When a `Status` field is present, the adapter includes only `Application Open`
rows by default. To include every status for a controlled backfill or test, use
`KsbitExportSource(path, allowed_statuses=None)` in code. The MVP CLI does not
expose a status override.

12Twenty work authorization values are mapped conservatively:

- `All Work Authorizations Accepted` and `STEM Eligible Degree` become
  `opt_cpt_flag=true`.
- `Permanent US Work Authorization Required`, US-citizen-only, green-card-only,
  or permanent-resident-only wording becomes `opt_cpt_flag=false`.
- Missing or ambiguous values remain `null` so downstream logic can treat them
  as unknown.

HTML job descriptions are converted to readable plain text for matching while
the original source description is preserved in raw metadata.

## Data Minimization

The adapter preserves source-row context in `raw_metadata["raw_payload"]` so
future reviewers can trace how a `JobPosting` was created. Datetimes are
serialized to ISO strings, blank and `NULL` source values are normalized to
`null`, and source row number/source format are recorded for spreadsheet
exports.

The Excel loader does not persist application/applicant analytics columns in
`raw_metadata`, including `Application Count`, `Distinct Applicant Count`,
`First Application Date`, and `Last Application Date`. Student- or
applicant-level analytics remain out of scope until explicitly approved.

Operational logs report file path, counts, and row-level warning summaries.
They intentionally do not log raw job descriptions, apply URLs, or full source
payloads.

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

## Configuration And Registry Metadata

Runtime settings:

- `APPROVED_JOBS_PATH`: default input for the `approved_json` source.
- `KSBIT_EXPORT_PATH`: default input for the `ksbit_export` source when
  `hope-job-agent run-pipeline --source ksbit_export` omits `--source-file`.
- `LOG_LEVEL`: controls application logging where runners call
  `configure_logging`.

The source registry marks `ksbit_export` as an approved local export source for
JSON/CSV/XLSX files only. The approved access method excludes live collection,
credentials, browser automation, and login/session workflows.

## Committed Synthetic 12Twenty Fixture

The real KelleyLink/12Twenty export contains student PII and cannot be committed.
`data/sample_12twenty_export.xlsx` is a committed, schema-faithful synthetic
export that mirrors the real dry-run column layout — JSON `Location` cells
(`{"CountryName":...,"CityName":"Chicago - IL"}`), `Status` values (open vs.
closed), work-authorization strings, and the sensitive analytics columns
(`Application Count`, `Distinct Applicant Count`) the adapter must drop — using
entirely fabricated data. It deliberately includes edge cases: a closed posting
(filtered by status), a row missing `Application URL` (skipped with a warning),
and a row missing `Job Posting ID` (fallback id generation).

Regenerate it with:

```bash
python scripts/generate_sample_12twenty_xlsx.py
```

This gives the Excel path deterministic test coverage of real schema variance
without exposing PII (see `tests/test_12twenty_fixture.py`).

## Future KSBIT API Path

A future API-backed source should preserve the same `BaseJobSource` contract and
return the same `JobPosting` fields. The API client can replace the local file
loader internally while keeping downstream pipeline logic unchanged.

Before adding a live integration, document approval in the source registry,
review access terms, and avoid credentials or session behavior in committed
code.

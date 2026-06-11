# MVP Pipeline Runner

MSI-21 adds one local command that runs the MVP job pipeline end to end using
approved local export source adapters. It does not scrape websites, automate a
browser, access LinkedIn, log in to Handshake, or require credentials.

## Command

```bash
python -m hope_job_agent.pipeline.run_mvp --source approved_json --input data/sample_jobs.json --profiles data/sample_profiles.json --output outputs/mvp_results.csv
```

Optional flags:

- `--limit N`: export at most `N` ranked jobs per consenting student profile.
- `--source-since-date YYYY-MM-DD`: for `ksbit_export`, include source records
  posted on or after the given date. Records without parseable dates are
  included with warnings.
- `--source-limit N`: for `ksbit_export`, return at most `N` source records
  after source filtering.
- `--dry-run`: execute ingestion, normalization, deduplication, classification,
  and ranking without writing output files.
- `--verbose`: enable debug logging.

KSBIT-compatible local exports can use the same runner:

```bash
python -m hope_job_agent.pipeline.run_mvp --source ksbit_export --input data/sample_ksbit_jobs.json --profiles data/sample_profiles.json --output outputs/ksbit_mvp_results.csv
```

## What It Does

The runner composes the Sprint 2 modules in this order:

1. Loads runtime config with `hope_job_agent.config.get_settings`.
2. Checks the source registry and loads an approved local source adapter.
3. Ingests raw jobs from the approved JSON export.
4. Normalizes job fields with `pipeline.normalize.normalize_job`.
5. Validates required job fields and warns on recoverable bad records.
6. Deduplicates with `pipeline.deduplicate.deduplicate_jobs`.
7. Classifies role and concentration tags with
   `classification.classifier.classify_job_posting`.
8. Loads local student profiles.
9. Ranks jobs per consenting profile with `scoring.ranker.rank_jobs_for_student`.
10. Exports a CSV or JSON results file.
11. Writes a summary JSON beside the results file.

## Input Format

For `approved_json`, job input must be an approved JSON export envelope:

```json
{
  "metadata": {
    "source_name": "approved_local_sample",
    "approved_by": "Project faculty advisor",
    "approval_date": "2026-06-02",
    "access_method": "Local approved JSON export for MVP development",
    "terms_reviewed": true
  },
  "jobs": [
    {
      "source_job_id": "sample-job-001",
      "title": "Data Analyst Intern",
      "company": "Example Analytics",
      "location": "Bloomington, IN",
      "description": "Use SQL and Python to analyze business data.",
      "url": "https://example.com/jobs/data-analyst-intern",
      "concentration_tags": ["Business Analytics"],
      "opt_cpt_flag": true
    }
  ]
}
```

Each job needs title, company, location, description, and one of `url`,
`apply_url`, or `post_url`. Optional fields include `source_job_id`,
`posted_date`, `employment_type`, `seniority`, `role_tags`,
`concentration_tags`, `opt_cpt_flag`, and `raw_metadata`.

For `ksbit_export`, job input can be a JSON list, wrapped JSON object, or CSV.
See `docs/ksbit_export_adapter.md` for supported wrappers, required fields, and
alias mappings.

Profiles can be a JSON array or an object with a `profiles` array. Each profile
uses the `StudentProfile` model fields, including `student_id`, `name`,
`concentration`, `academic_stage`, `target_roles`, `skills`,
`work_auth_status`, and `ai_matching_consent`.

## Output Fields

The CSV/JSON export includes:

- `student_id`
- `student_name`
- `title`
- `company`
- `location`
- `source`
- `apply_url/post_url`
- `role_category`
- `target_role`
- `concentration_tags`
- `seniority_level`
- `opt_cpt_flag`
- `final_score`
- `score_breakdown`
- `ranking_explanation`

The summary file is named beside the output path. For
`outputs/mvp_results.csv`, the summary is `outputs/mvp_results.summary.json`.
It includes run ID, timestamp, paths, counts for raw/normalized/duplicate/
unique/classified jobs, profile counts, total ranked matches, warnings, errors,
and runtime seconds.

## Known Limitations

- MVP v1 supports approved local exports through `approved_json` and
  `ksbit_export`.
- Ranking is deterministic and rule-based; it does not call an LLM.
- The classifier is deterministic and keyword-based.
- Location preferences are captured in profiles but not yet scored.
- Bad individual job records are skipped with warnings when the export envelope
  is otherwise valid. Missing files, malformed JSON, empty job/profile files,
  invalid profiles, and unwritable output paths fail the run.

## Compliance

This runner is intentionally local-first. Add new sources only after registry
metadata and approval review. Do not add scraping, login automation, session
circumvention, CAPTCHA bypassing, proxy rotation, LinkedIn scraping, or
Handshake login scraping.

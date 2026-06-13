# GCS Trend Outputs

## Purpose

GCS-facing trend outputs provide Graduate Career Services with program-level
job-market intelligence rather than student-personalized rankings. The early
outputs are intended for spreadsheets, dashboards, scheduled reports, and
advisor discussions about employer activity and hiring demand.

## Assumed `job_postings` Fields

The SQL drafts assume one normalized, deduplicated row per posting in a table
named `job_postings`.

| Field | Expected use |
| --- | --- |
| `source` | Approved adapter or export that supplied the posting |
| `title` | Job title used for role-mix analysis |
| `company` | Employer name used for employer trends |
| `location` | Location text used for city, state, and remote trends |
| `description` | Posting description available for future analysis |
| `url` | Posting identifier used during deduplication |
| `posted_date` | Source-reported posting date |
| `concentration_tags` | One or more MSIS concentration classifications |
| `opt_cpt_flag` | Whether a posting is marked OPT/CPT friendly |
| `ingested_at` or `retrieval_date` | Date or timestamp when the pipeline retrieved the posting |

## Early GCS-Facing Metrics

| Metric | Definition |
| --- | --- |
| Employer count | Number of unique employers represented in the selected period |
| Top employers | Employers with the highest posting counts |
| Repeated employers | Employers with more than one posting in the selected period |
| Role mix | Posting distribution across broad roles inferred from title keywords |
| Concentration mix | Posting distribution across MSIS concentration tags |
| Location trends | Posting counts by location text or remote status |
| Posting freshness | Posting counts grouped by age since `posted_date` |
| OPT/CPT-friendly postings | Count of postings where `opt_cpt_flag` is true |
| New postings by date/month | Posting volume grouped by day or month |

## SQL/Query Drafts

PostgreSQL-style query drafts are maintained in
`sql/gcs_trend_queries.sql`. The file includes:

1. Unique employer count
2. Postings by source
3. Top employers
4. Repeated employers
5. Role mix using title keywords
6. Concentration mix using `concentration_tags`
7. Location trends
8. Posting freshness by age bucket
9. OPT/CPT-friendly posting count
10. New postings by date
11. Monthly posting trend

## Notes and Assumptions

- Final SQL may need adjustment after the database schema is finalized.
- The concentration-mix query depends on whether `concentration_tags` are
  stored as an array, JSON field, or separate join table.
- Queries should run against normalized and deduplicated postings.
- Missing `posted_date` values should be reported separately or excluded from
  freshness and date-based metrics.
- `ingested_at` and `retrieval_date` represent the same reporting concept; the
  final schema should standardize on one field name.
- Role groups based on title keywords are an early approximation and may later
  use classifier-generated role tags.
- Trend reports should include source name and retrieval date for traceability.

## Future Enhancements

Based on GCS feedback, future outputs may include student-progress metrics such
as application activity, interview progress, offer outcomes, advising
touchpoints, and placement status. These metrics require approved access to
student-level systems such as KelleyLink, Handshake, or advising platforms and
must follow applicable privacy, access-control, and data-retention policies.

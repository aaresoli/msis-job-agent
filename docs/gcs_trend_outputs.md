# GCS Trend Outputs

## Purpose

GCS-facing trend outputs provide Graduate Career Services with an on-demand,
program-level view of job opportunities and recruiting activity. The outputs
support career coaching and employer-trend discussions without exposing
student-level activity.

## Assumed `job_postings` Fields

The query drafts assume one normalized, deduplicated row per posting in a table
named `job_postings`.

| Field | Expected use | Confirmation status |
| --- | --- | --- |
| `source` | Approved adapter or export that supplied the posting | Expected |
| `title` | Job title used for role classification | Expected |
| `company` | Employer name used for employer trends | Expected |
| `location` | Location text used for geographic and remote trends | Expected |
| `description` | Posting description available for future analysis | Expected |
| `url` | Posting identifier used during deduplication | Expected |
| `posted_date` | Source-reported posting date | Expected but may be missing |
| `concentration_tags` | One or more MSIS concentration classifications | Storage format unconfirmed |
| `opt_cpt_flag` | Explicit OPT/CPT-friendly indicator | Availability unconfirmed |
| `retrieval_date` or `ingested_at` | Date or timestamp when the posting was retrieved | Field name unconfirmed |
| Active status or expiration date | Determines whether a posting remains active | Not yet confirmed |

## GCS Dashboard Metrics

### 1. Job Market Overview

- Total active postings, using a documented 90-day posting-age proxy until an
  active-status or expiration field is confirmed.
- New postings this week.
- Unique employers.
- Posting count by approved source.
- Top employers and repeated employers.
- Top locations and role categories.
- Posting freshness by age bucket.
- New postings by date and month.

### 2. Concentration Insights

For each MSIS concentration:

- Posting count.
- Top role categories.
- Top employers.
- Top locations.

The SQL drafts assume `concentration_tags` is a PostgreSQL text array. They must
be adjusted if the final schema uses JSON or a separate join table.

### 3. OPT/CPT Opportunities

- Total postings explicitly marked OPT/CPT friendly.
- New OPT/CPT-friendly postings this week.
- Top employers with OPT/CPT-friendly postings.
- Top locations for OPT/CPT-friendly postings.

OPT/CPT availability in KelleyLink is not confirmed. Counts must include only
records explicitly marked `true`; missing values remain unknown and must not be
inferred from title, company, description, or location.

### 4. Employer Activity

- Employer name.
- Posting count.
- Recent roles posted.
- Approved source.
- Last retrieval date.

The final retrieval field may be named `retrieval_date` or `ingested_at`. The
query draft uses `retrieval_date` as a placeholder until the schema is settled.

### 5. Recruiting Events

When an approved event schema is available, the dashboard may show:

- Employer name.
- Event name and type.
- Event date.
- Related concentration or role, when available.

KelleyLink includes event information broadly, but no project-specific Denodo
view, endpoint, or export exists yet. The event query remains commented out
until the event fields and employer join key are approved.

## SQL/Query Drafts

PostgreSQL-style drafts are maintained in `sql/gcs_trend_queries.sql`. They
cover the five dashboard sections while documenting unconfirmed fields and
temporary assumptions.

## Source and Access Assumptions

- KelleyLink job-posting access depends on KSBIT creating a Denodo view,
  endpoint, or scheduled export after the required fields are confirmed.
- No project-specific KelleyLink API endpoint currently exists.
- Handshake currently provides past and upcoming interview schedules and is not
  confirmed for MVP job-posting ingestion.
- Direct Handshake API integration is not part of the MVP.
- Refresh frequency for KSBIT endpoints or exports is not finalized.
- OPT/CPT, active status, expiration date, retrieval date, and the final
  `concentration_tags` representation remain unconfirmed.
- Queries must run against approved, normalized, and deduplicated records.

## Out of Scope

The MSI-34 trend outputs do not include:

- Student-level tracking or individual student progress.
- Application analytics or application status.
- Interview status analytics.
- Offer tracking or outcomes.
- Alumni matching or alumni analytics.
- Recruiter contact analytics or recommendations.

Those capabilities require separate approval, privacy review, access controls,
and confirmed source schemas.

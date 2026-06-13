# GCS Trend Outputs

## 1. Purpose

This document defines early trend outputs for Graduate Career Services (GCS).
These outputs provide program-level job-market visibility rather than
student-personalized rankings. They are intended as a starting point for
spreadsheets, dashboards, scheduled reports, and future database queries.

## 2. Assumed Job Table Fields

The query drafts assume a normalized table named `job_postings` with fields
based on the shared `JobPosting` model and ingestion pipeline:

| Field | Expected use |
| --- | --- |
| `source` | Identifies the approved source adapter or export |
| `title` | Supports role-mix classification and keyword analysis |
| `company` | Supports employer counts and top-employer reporting |
| `location` | Supports city, state, and remote-work trends |
| `description` | Supports future skill and role analysis |
| `url` | Identifies the posting and supports deduplication |
| `posted_date` | Supports freshness and monthly trend reporting |
| `concentration_tags` | Supports concentration-mix reporting |
| `opt_cpt_flag` | Identifies postings marked as OPT/CPT friendly |
| `ingested_at` or `retrieval_date` | Records when the pipeline retrieved the posting |

## 3. Early GCS-Facing Metrics

| Metric | Definition |
| --- | --- |
| Employer count | Number of unique employers represented in the selected period |
| Role mix | Distribution of postings across broad role groups inferred from title keywords |
| Concentration mix | Distribution of postings across MSIS concentration tags |
| Location trends | Posting counts by city, state, or remote status |
| Posting freshness | Posting counts grouped by age since `posted_date` |
| Postings by source | Posting volume contributed by each approved source |
| Top employers | Employers with the highest posting counts |
| OPT/CPT-friendly posting count | Count of postings where `opt_cpt_flag` is true |
| Monthly posting trend | Posting volume grouped by posting month |

## 4. SQL/Query Drafts

The examples use PostgreSQL-style syntax and assume one row per normalized,
deduplicated job posting.

### Unique Employer Count

```sql
select count(distinct company) as employer_count
from job_postings
where posted_date >= current_date - interval '90 days';
```

### Postings by Source

```sql
select source, count(*) as posting_count
from job_postings
group by source
order by posting_count desc;
```

### Top Employers by Posting Count

```sql
select company, count(*) as posting_count
from job_postings
group by company
order by posting_count desc, company
limit 20;
```

### Role Mix Using Title Keywords

```sql
select
  case
    when lower(title) like '%security%' or lower(title) like '%cyber%'
      then 'Cybersecurity'
    when lower(title) like '%data%' or lower(title) like '%analytics%'
      then 'Data and Analytics'
    when lower(title) like '%consult%' or lower(title) like '%strategy%'
      then 'IT Strategy and Consulting'
    when lower(title) like '%system%' or lower(title) like '%erp%'
      then 'Enterprise Systems'
    else 'Other'
  end as role_group,
  count(*) as posting_count
from job_postings
group by role_group
order by posting_count desc;
```

### Concentration Mix Using Concentration Tags

```sql
select concentration_tag, count(*) as posting_count
from job_postings
cross join lateral unnest(concentration_tags) as concentration_tag
group by concentration_tag
order by posting_count desc;
```

### Location Trends by City, State, or Remote Status

```sql
select
  case
    when lower(location) like '%remote%' then 'Remote'
    else location
  end as location_group,
  count(*) as posting_count
from job_postings
group by location_group
order by posting_count desc;
```

### Posting Freshness by Age Bucket

```sql
select
  case
    when posted_date >= current_date - interval '7 days' then '0-7 days'
    when posted_date >= current_date - interval '30 days' then '8-30 days'
    when posted_date >= current_date - interval '60 days' then '31-60 days'
    when posted_date >= current_date - interval '90 days' then '61-90 days'
    else 'Over 90 days'
  end as freshness_bucket,
  count(*) as posting_count
from job_postings
group by freshness_bucket
order by min(current_date - posted_date);
```

### OPT/CPT-Friendly Posting Count

```sql
select count(*) as opt_cpt_friendly_posting_count
from job_postings
where opt_cpt_flag is true;
```

### Monthly Posting Trend

```sql
select
  date_trunc('month', posted_date) as posting_month,
  count(*) as posting_count
from job_postings
where posted_date is not null
group by posting_month
order by posting_month;
```

## 5. Notes and Assumptions

- Final SQL may need adjustment after the database schema is finalized.
- The concentration-mix query depends on whether `concentration_tags` are
  stored as an array, JSON field, or separate join table.
- Queries should run against normalized and deduplicated postings.
- Missing `posted_date` values should be reported separately or excluded from
  freshness and monthly trend metrics.
- `ingested_at` and `retrieval_date` represent the same reporting concept; the
  final schema should standardize on one field name.
- Role groups based on title keywords are an early approximation and may later
  use classifier-generated role tags.
- Trend reports should include source name and retrieval date for traceability.

<!-- from interview note: Future GCS-facing outputs may include student-progress metrics if approved access to Handshake, KelleyLink, or advising systems becomes available. GCS feedback indicates a strong interest in centralized student progress tracking and advisor workflow support. -->
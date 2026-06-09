# GCS Trend Outputs

The GCS-facing output is program-level market intelligence, not a
student-personalized ranking. V0 fields should be interpretable in spreadsheets
or dashboards.

## Fields

- `company`
- `role_category`
- `concentration_track`
- `location`
- `posted_date`
- `source`
- `seniority`
- `employment_type`
- `opt_cpt_signal`
- `skill_keywords`
- `posting_count`
- `first_seen_date`
- `last_seen_date`

## Draft SQL

```sql
select
  company,
  unnest(role_tags) as role_category,
  unnest(concentration_tags) as concentration_track,
  location,
  source,
  seniority,
  employment_type,
  opt_cpt_flag as opt_cpt_signal,
  date_trunc('week', posted_date) as posting_week,
  count(*) as posting_count,
  min(created_at) as first_seen_date,
  max(updated_at) as last_seen_date
from normalized_job_postings
where posted_date >= current_date - interval '90 days'
group by
  company,
  role_category,
  concentration_track,
  location,
  source,
  seniority,
  employment_type,
  opt_cpt_signal,
  posting_week
order by posting_week desc, posting_count desc;
```

## Track Count Note

The project brief references all 5 concentration tracks, while the current
validated schema contains 4 tracks. Sprint 3 should confirm the official fifth
track name with the advisor before changing schema vocabulary.

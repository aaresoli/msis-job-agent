-- GCS dashboard query drafts for PostgreSQL.
--
-- KelleyLink access depends on KSBIT creating an approved Denodo view,
-- endpoint, or scheduled export. No project-specific endpoint exists yet.
-- Handshake is not confirmed for MVP job-posting ingestion.
--
-- These drafts assume concentration_tags is a PostgreSQL text array and use
-- retrieval_date as the retrieval field. Both assumptions may need adjustment
-- after the final schema is confirmed. OPT/CPT availability, active status,
-- expiration date, and retrieval date are still unconfirmed.
--
-- Student, application, interview, offer, alumni, and recruiter analytics are
-- outside the scope of these queries.

-- 1. Total active postings using a 90-day age-window proxy.
-- Replace this proxy when an approved active-status or expiration field exists.
select count(*) as active_posting_count
from job_postings
where posted_date >= current_date - interval '90 days';

-- 2. New postings this week.
-- Use retrieval_date only when posted_date is unavailable or unreliable.
select count(*) as new_posting_count
from job_postings
where coalesce(posted_date, retrieval_date)
      >= date_trunc('week', current_date)::date;

-- 3. Unique employer count.
select count(distinct company) as employer_count
from job_postings
where company is not null;

-- 4. Posting count by source.
select source, count(*) as posting_count
from job_postings
group by source
order by posting_count desc, source;

-- 5. Top employers.
select company, count(*) as posting_count
from job_postings
where company is not null
group by company
order by posting_count desc, company
limit 20;

-- 6. Repeated employers.
select company, count(*) as posting_count
from job_postings
where company is not null
group by company
having count(*) > 1
order by posting_count desc, company;

-- 7. Top locations.
select
  case
    when lower(location) like '%remote%' then 'Remote'
    when location is null or trim(location) = '' then 'Unknown'
    else location
  end as location_group,
  count(*) as posting_count
from job_postings
group by location_group
order by posting_count desc, location_group
limit 20;

-- 8. Top role categories using title keywords.
select
  case
    when lower(title) like '%security%' or lower(title) like '%cyber%'
      then 'Cybersecurity Analyst'
    when lower(title) like '%data%' or lower(title) like '%analytics%'
      then 'Data Analyst / BI Engineer'
    when lower(title) like '%consult%' or lower(title) like '%strategy%'
      then 'IT Consultant / Tech Risk'
    when lower(title) like '%digital%' or lower(title) like '%automation%'
      then 'Product / Project Manager'
    when lower(title) like '%system%' or lower(title) like '%erp%'
      then 'IT Consultant / Tech Risk'
    else 'Other'
  end as role_group,
  count(*) as posting_count
from job_postings
group by role_group
order by posting_count desc, role_group;

-- 9. Posting count by concentration.
-- This draft assumes concentration_tags is a PostgreSQL text array.
select concentration_tag, count(*) as posting_count
from job_postings
cross join lateral unnest(concentration_tags) as concentration_tag
group by concentration_tag
order by posting_count desc, concentration_tag;

-- 10. Roles by concentration.
with classified_jobs as (
  select
    concentration_tag,
    case
      when lower(title) like '%security%' or lower(title) like '%cyber%'
        then 'Cybersecurity Analyst'
      when lower(title) like '%data%' or lower(title) like '%analytics%'
        then 'Data Analyst / BI Engineer'
      when lower(title) like '%consult%' or lower(title) like '%strategy%'
        then 'IT Consultant / Tech Risk'
      when lower(title) like '%digital%' or lower(title) like '%automation%'
        then 'Product / Project Manager'
      when lower(title) like '%system%' or lower(title) like '%erp%'
        then 'IT Consultant / Tech Risk'
      else 'Other'
    end as role_group
  from job_postings
  cross join lateral unnest(concentration_tags) as concentration_tag
)
select concentration_tag, role_group, count(*) as posting_count
from classified_jobs
group by concentration_tag, role_group
order by concentration_tag, posting_count desc, role_group;

-- 11. Top employers by concentration.
select concentration_tag, company, count(*) as posting_count
from job_postings
cross join lateral unnest(concentration_tags) as concentration_tag
where company is not null
group by concentration_tag, company
order by concentration_tag, posting_count desc, company;

-- 12. Top locations by concentration.
select
  concentration_tag,
  case
    when lower(location) like '%remote%' then 'Remote'
    when location is null or trim(location) = '' then 'Unknown'
    else location
  end as location_group,
  count(*) as posting_count
from job_postings
cross join lateral unnest(concentration_tags) as concentration_tag
group by concentration_tag, location_group
order by concentration_tag, posting_count desc, location_group;

-- 13. Posting freshness by age bucket.
-- The CTE provides a stable numeric sort key for PostgreSQL.
with posting_freshness as (
  select
    case
      when posted_date is null then 'Unknown'
      when posted_date >= current_date - interval '7 days' then '0-7 days'
      when posted_date >= current_date - interval '30 days' then '8-30 days'
      when posted_date >= current_date - interval '60 days' then '31-60 days'
      when posted_date >= current_date - interval '90 days' then '61-90 days'
      else 'Over 90 days'
    end as freshness_bucket,
    case
      when posted_date is null then 6
      when posted_date >= current_date - interval '7 days' then 1
      when posted_date >= current_date - interval '30 days' then 2
      when posted_date >= current_date - interval '60 days' then 3
      when posted_date >= current_date - interval '90 days' then 4
      else 5
    end as bucket_order
  from job_postings
)
select freshness_bucket, count(*) as posting_count
from posting_freshness
group by freshness_bucket, bucket_order
order by bucket_order;

-- 14. OPT/CPT-friendly posting count.
-- Count only explicit true values; null remains unknown.
select count(*) as opt_cpt_friendly_posting_count
from job_postings
where opt_cpt_flag is true;

-- 15. New OPT/CPT-friendly postings this week.
select count(*) as new_opt_cpt_friendly_posting_count
from job_postings
where opt_cpt_flag is true
  and coalesce(posted_date, retrieval_date)
      >= date_trunc('week', current_date)::date;

-- 16. Top employers with OPT/CPT-friendly postings.
select company, count(*) as posting_count
from job_postings
where opt_cpt_flag is true
  and company is not null
group by company
order by posting_count desc, company
limit 20;

-- 17. Top locations for OPT/CPT-friendly postings.
select
  case
    when lower(location) like '%remote%' then 'Remote'
    when location is null or trim(location) = '' then 'Unknown'
    else location
  end as location_group,
  count(*) as posting_count
from job_postings
where opt_cpt_flag is true
group by location_group
order by posting_count desc, location_group
limit 20;

-- 18. Employer activity with recent roles, source, and retrieval date.
-- Rename retrieval_date if the final schema standardizes on ingested_at.
select
  company,
  source,
  count(*) as posting_count,
  string_agg(distinct title, ', ' order by title) as recent_roles,
  max(retrieval_date) as last_retrieved_date
from job_postings
where company is not null
group by company, source
order by posting_count desc, company, source;

-- 19. New postings by date.
select
  coalesce(posted_date, retrieval_date) as activity_date,
  count(*) as new_posting_count
from job_postings
group by activity_date
order by activity_date;

-- 20. Monthly posting trend.
select
  date_trunc('month', coalesce(posted_date, retrieval_date))::date
    as posting_month,
  count(*) as posting_count
from job_postings
group by posting_month
order by posting_month;

-- 21. Optional recruiting-event query.
-- This query is intentionally disabled until KSBIT supplies an approved event
-- schema and a reliable employer join key. KelleyLink broadly includes events,
-- but no project-specific Denodo view, endpoint, or export exists yet.
--
-- select
--   employer_name,
--   event_name,
--   event_type,
--   event_date,
--   related_concentration,
--   related_role
-- from recruiting_events
-- where event_date >= current_date
-- order by event_date, employer_name;

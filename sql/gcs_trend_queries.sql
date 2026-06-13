-- GCS trend-output query drafts for PostgreSQL.
--
-- These queries may need adjustment once the final database schema is
-- confirmed. In particular, concentration_tags may be stored as a PostgreSQL
-- array, a JSON field, or records in a separate join table.

-- 1. Unique employer count
select count(distinct company) as employer_count
from job_postings
where company is not null;

-- 2. Postings by source
select source, count(*) as posting_count
from job_postings
group by source
order by posting_count desc, source;

-- 3. Top employers
select company, count(*) as posting_count
from job_postings
where company is not null
group by company
order by posting_count desc, company
limit 20;

-- 4. Repeated employers
select company, count(*) as posting_count
from job_postings
where company is not null
group by company
having count(*) > 1
order by posting_count desc, company;

-- 5. Role mix using title keywords
select
  case
    when lower(title) like '%security%' or lower(title) like '%cyber%'
      then 'Cybersecurity'
    when lower(title) like '%data%' or lower(title) like '%analytics%'
      then 'Data and Analytics'
    when lower(title) like '%consult%' or lower(title) like '%strategy%'
      then 'IT Strategy and Consulting'
    when lower(title) like '%digital%' or lower(title) like '%automation%'
      then 'Digital Enterprise Systems'
    when lower(title) like '%system%' or lower(title) like '%erp%'
      then 'Enterprise Systems'
    else 'Other'
  end as role_group,
  count(*) as posting_count
from job_postings
group by role_group
order by posting_count desc, role_group;

-- 6. Concentration mix using concentration_tags.
-- This draft assumes concentration_tags is a PostgreSQL text array.
select concentration_tag, count(*) as posting_count
from job_postings
cross join lateral unnest(concentration_tags) as concentration_tag
group by concentration_tag
order by posting_count desc, concentration_tag;

-- 7. Location trends
select
  case
    when lower(location) like '%remote%' then 'Remote'
    when location is null or trim(location) = '' then 'Unknown'
    else location
  end as location_group,
  count(*) as posting_count
from job_postings
group by location_group
order by posting_count desc, location_group;

-- 8. Posting freshness by age bucket
select
  case
    when posted_date is null then 'Unknown'
    when posted_date >= current_date - interval '7 days' then '0-7 days'
    when posted_date >= current_date - interval '30 days' then '8-30 days'
    when posted_date >= current_date - interval '60 days' then '31-60 days'
    when posted_date >= current_date - interval '90 days' then '61-90 days'
    else 'Over 90 days'
  end as freshness_bucket,
  count(*) as posting_count
from job_postings
group by freshness_bucket
order by
  case freshness_bucket
    when '0-7 days' then 1
    when '8-30 days' then 2
    when '31-60 days' then 3
    when '61-90 days' then 4
    when 'Over 90 days' then 5
    else 6
  end;

-- 9. OPT/CPT-friendly posting count
select count(*) as opt_cpt_friendly_posting_count
from job_postings
where opt_cpt_flag is true;

-- 10. New postings by date
select posted_date, count(*) as new_posting_count
from job_postings
where posted_date is not null
group by posted_date
order by posted_date;

-- 11. Monthly posting trend
select
  date_trunc('month', posted_date)::date as posting_month,
  count(*) as posting_count
from job_postings
where posted_date is not null
group by posting_month
order by posting_month;

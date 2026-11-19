# MVP Source Assumptions

## 1. Purpose

This document records confirmed KSBIT/GCS source findings and access
assumptions for the MVP. It is intended to keep the ingestion scope clear
before any source-specific endpoint, export, or reporting work is implemented.

## 2. Confirmed Source Findings

- Handshake is currently limited to past and upcoming interview schedules.
- Handshake is not currently confirmed as a broad job-posting source.
- KelleyLink is broad and includes companies, contacts/reps, events, job
  postings, interview schedules, employment outcomes, and student data.
- No project-specific API endpoints exist yet.
- KSBIT can build Denodo views/endpoints once the team defines exactly what
  data is needed.
- KSBIT can create and schedule reports/exports once the team defines the query
  requirements.

## 3. Access Assumptions

- The MVP should use only approved sources, approved exports, Denodo
  views/endpoints, or KSBIT-created scheduled reports.
- KelleyLink is the strongest candidate for broad job-posting data if KSBIT
  creates a Denodo view, endpoint, or scheduled export.
- Handshake should not be treated as a broad job-posting source unless GCS/KSBIT
  later confirms access to relevant job-posting data.
- No direct external platform integration should be built until the access
  method, allowed fields, and compliance expectations are confirmed.

## 4. Refresh Frequency Assumptions

- Refresh frequency is not finalized.
- Scheduled exports may be daily, weekly, or on another cadence selected by GCS
  and KSBIT.
- Denodo views/endpoints may support fresher access, but the project should
  follow KSBIT-defined performance and rate-limit expectations.
- Trend reporting should record `retrieval_date` or `ingested_at` so reports can
  distinguish newly retrieved postings from older postings.

## 5. Missing or Unconfirmed Fields

- Exact KelleyLink job-posting fields.
- Whether sponsorship, OPT, or CPT indicators exist in KelleyLink.
- Whether application-level data can be used.
- Whether student-level data can be used.
- Whether employer contact/rep fields can be included in MVP reporting.
- Final Denodo view, endpoint, or export schema.
- Final refresh cadence and historical backfill expectations.

## 6. Source Limitations

- Handshake is currently limited to interview schedules and is not confirmed for
  broad job-posting ingestion.
- No project-specific API endpoints exist yet.
- Data access depends on KSBIT creating views, endpoints, reports, or exports
  after the team defines the required fields and queries.
- Student-level and applicant-level data require explicit approval before use.
- Unapproved public or private sources must remain out of scope.

## 7. MVP Will Support

- Approved-source ingestion.
- KelleyLink job-posting data if a Denodo view/endpoint is created.
- Company/employer information.
- Job-posting trend outputs.
- Concentration-based classification.
- GCS-facing reporting outputs.

## 8. MVP Will Not Support

- LinkedIn scraping.
- Direct Handshake job-posting ingestion.
- Direct Handshake API integration.
- Login automation.
- CAPTCHA bypassing.
- Unapproved source collection.
- Student-level tracking unless approved.
- Applicant-level analytics unless approved.

## 9. Open Questions

- What exact KelleyLink job-posting fields will be available?
- What refresh frequency should scheduled exports/endpoints use?
- Do sponsorship, OPT, or CPT indicators exist in the available KelleyLink data?
- Can application-level data be used?
- Can student-level data be used?
- What is the final Denodo view/API schema?

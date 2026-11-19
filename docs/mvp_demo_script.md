# MVP Sprint Review Demo Script

## 1. Demo Goal

Demonstrate that HOPE turns approved job-source data into clear student and GCS
outcomes. The demo follows one job record from ingestion through normalization,
deduplication, classification, matching, and reporting without relying on live
or unapproved integrations.

## 2. Demo Setup

Before the review:

1. Run the automated tests and the demo command once.
2. Keep the approved input, generated output, student template, GCS dashboard
   template, SQL draft, and source assumptions open in presentation order.
3. Keep a generated CSV available as a fallback if the live command cannot run.

Use this prepared command:

```powershell
python -m hope_job_agent.pipeline.run_mvp `
  --source approved_json `
  --input data/sample_jobs.json `
  --profiles data/sample_profiles.json `
  --output outputs/mvp_results.csv
```

**Target demo time:** 8-10 minutes.

## 3. Step-by-Step Demo Flow

### Step 1: Show the Approved Source Input (45 seconds)

**Show on screen**

Open `data/sample_jobs.json`. Point out the approval metadata and a few job
fields such as title, company, location, description, URL, and posted date.

**Say**

"The MVP begins with an approved local export. This demonstrates the source
adapter contract without scraping or connecting to an unapproved platform."

**Outcome to emphasize**

The starting data is realistic, traceable, and compliant with the MVP source
boundaries.

### Step 2: Run or Describe Source Ingestion (1 minute)

**Show on screen**

Run the prepared command and point out the selected source, input file, student
profiles, and output path.

**Say**

"The approved-source adapter loads the export and sends accepted records into
the shared pipeline. The architecture can support additional adapters once
their access methods and fields are approved."

**Outcome to emphasize**

The run completes and creates the expected output. If execution is unavailable,
open the prepared CSV and briefly describe the command.

### Step 3: Show Normalized, Deduplicated, and Classified Postings

**Estimated time:** 1 minute 15 seconds

**Show on screen**

Display representative generated records. Highlight normalized title, company,
location, source, dates, role category, and concentration classification. Point
out the source and final posting counts.

**Say**

"The pipeline converts source-specific records into one consistent job
structure, removes duplicate postings, and applies shared role and
concentration classifications. Downstream matching and reporting therefore do
not depend on the original export format."

**Outcome to emphasize**

Approved source records become clean, unique, and consistently classified job
postings.

### Step 4: Show the Student Weekly Digest Template

**Estimated time:** 1 minute 15 seconds

**Show on screen**

Open `docs/mvp_output_student_template.md`. Start with the sample email so the
audience sees the student-facing outcome immediately.

**Say**

"The student MVP output is a weekly, action-oriented email. It lists every
matching opportunity in one ranked list, includes a short explanation and
apply link, and places a related employer event beneath the job when approved
event data is available."

**Outcome to emphasize**

Students receive a focused list of actions rather than a labor-market dashboard
or an unexplained score.

### Step 5: Explain Ranking Logic and Match Reasons (1 minute)

**Show on screen**

Use `data/sample_profiles.json` alongside the student digest or generated match
output. Compare profile preferences with the first few ranked jobs and their
match reasons.

**Say**

"For a student who requires OPT/CPT, postings explicitly marked friendly come
first. The remaining ordering uses match strength and then posting recency.
Each short match reason connects the recommendation to profile and job fields."

**Outcome to emphasize**

The ordering is understandable, deterministic, and tied to visible evidence.
Unknown OPT/CPT values remain unknown and are not inferred.

### Step 6: Show the GCS Dashboard Template

**Estimated time:** 1 minute 15 seconds

**Show on screen**

Open `docs/mvp_output_gcs_dashboard_template.md`. Walk through Job Market
Overview, Concentration Insights, OPT/CPT Opportunities, Employer Activity, and
Recruiting Events.

**Say**

"GCS receives a separate on-demand dashboard concept focused on aggregate job,
employer, concentration, and location trends. It supports coaching discussions
without exposing individual student progress."

**Outcome to emphasize**

GCS gets an accessible program-level view that is clearly distinct from the
student weekly email.

### Step 7: Show the GCS Trend SQL Draft (1 minute)

**Show on screen**

Open `docs/gcs_trend_outputs.md` and `sql/gcs_trend_queries.sql`. Highlight the
active-posting proxy, concentration breakdowns, OPT/CPT queries, employer
activity, and optional event query.

**Say**

"These PostgreSQL-style drafts map the dashboard sections to concrete query
logic. They also identify fields that must be confirmed before the dashboard is
connected to a final database schema."

**Outcome to emphasize**

The dashboard is backed by defined metric logic rather than presentation-only
mockups.

### Step 8: Explain Source Assumptions and MVP Limitations (45 seconds)

**Show on screen**

Open `docs/mvp_source_assumptions.md` and finish on its support boundaries.

**Say**

"KelleyLink is the leading broad source candidate, but project-specific access
depends on KSBIT creating a Denodo view, endpoint, or scheduled export.
Handshake is currently limited to interview schedules and is not confirmed for
MVP job ingestion. The demo proves the architecture with approved samples
rather than claiming unavailable live integrations."

**Outcome to emphasize**

Reviewers understand exactly what works today, what depends on approved access,
and what remains future work.

**Total planned step time:** approximately 8 minutes 15 seconds, leaving time
for transitions or one brief question.

## 4. Expected Outcome

By the end of the demo, reviewers should understand that the MVP:

- Loads approved source exports.
- Normalizes, validates, deduplicates, and classifies postings.
- Produces explainable ranked student matches.
- Defines an actionable student weekly digest.
- Defines an on-demand GCS dashboard and supporting query drafts.
- Provides a compliant path toward additional approved sources.

## 5. Known Limitations to Mention

- KelleyLink requires a KSBIT Denodo view, endpoint, or scheduled export.
- Handshake is not confirmed for broad job-posting ingestion.
- OPT/CPT, active status, expiration, and retrieval fields remain unconfirmed.
- Recruiting-event output depends on an approved event schema.
- The GCS SQL is a draft pending the final database schema.
- Student-level tracking is not part of the MVP.
- Application, interview, offer, alumni, and recruiter analytics are not MVP
  features.
- No LinkedIn scraping, login automation, CAPTCHA bypassing, proxy rotation, or
  unapproved collection is supported.

## 6. Future Roadmap

- Confirm the KelleyLink job and event fields with GCS and KSBIT.
- Define and build an approved Denodo view, endpoint, or scheduled export.
- Finalize refresh frequency and retrieval-date handling.
- Confirm whether approved OPT/CPT or sponsorship indicators are available.
- Connect the GCS dashboard to a finalized database schema.
- Generate student email and GCS dashboard outputs from the live approved
  pipeline.
- Consider student, application, alumni, or recruiter capabilities only after
  explicit approval, privacy review, and access-control design.

## 7. Demo Summary

Close with this statement:

"The HOPE MVP demonstrates approved source ingestion, job normalization,
deduplication, classification, student matching, student-facing outputs, and
GCS-facing reporting. It does this within documented approved-source and
privacy boundaries, with a clear path toward KelleyLink and KSBIT integration
once the required access and schemas are approved."

The MVP demonstrates:

- Approved source ingestion
- Job normalization
- Deduplication
- Classification
- Student matching
- Student-facing outputs
- GCS-facing reporting
- Compliance with approved-source boundaries

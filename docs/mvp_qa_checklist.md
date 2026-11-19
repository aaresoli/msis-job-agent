# MVP QA Checklist

Use this checklist before the Sprint 3 review to confirm that the HOPE MVP
works end to end and that the demo stays within the approved scope.

## 1. Source Loading

- [ ] The selected source is listed as approved or approved for the demo.
- [ ] The approved JSON sample loads successfully.
- [ ] The KSBIT-compatible JSON or CSV sample loads successfully when used.
- [ ] The adapter health check succeeds where implemented.
- [ ] Jobs are ingested from the selected source.
- [ ] Source name and retrieval context are preserved.
- [ ] Missing, empty, malformed, or unsupported source files fail clearly.
- [ ] No live or unapproved source is required for the demo.

## 2. Required Job Fields

- [ ] Every accepted posting has a source.
- [ ] Every accepted posting has a title.
- [ ] Every accepted posting has a company.
- [ ] Every accepted posting has a location.
- [ ] Every accepted posting has a description.
- [ ] Every accepted posting has a valid application URL.
- [ ] Posted date is parsed when supplied.
- [ ] Concentration tags use supported taxonomy values.
- [ ] Missing OPT/CPT values remain unknown rather than being inferred.
- [ ] Invalid records are rejected or clearly surfaced.

## 3. Deduplication

- [ ] Duplicate postings are removed.
- [ ] URL normalization catches trailing-slash and case-only duplicates.
- [ ] First-seen ordering or the documented winner rule is preserved.
- [ ] Similar but distinct jobs are not incorrectly removed.
- [ ] The final posting count reflects deduplicated results.

## 4. Classification

- [ ] Every demo posting receives the expected role classification.
- [ ] Concentration classifications use the supported MSIS taxonomy.
- [ ] Unknown or unsupported tags are handled predictably.
- [ ] Analytics, cybersecurity, enterprise systems, digital systems, and
      strategy/consulting examples classify sensibly.
- [ ] Classification output is visible in the generated results.

## 5. Ranking

- [ ] Student profiles load successfully.
- [ ] Every matching opportunity receives a score or match label.
- [ ] More relevant opportunities rank above weaker matches.
- [ ] OPT/CPT-friendly jobs rank first when the student requires OPT/CPT.
- [ ] Match strength is the next sorting criterion.
- [ ] More recent posting dates break remaining ties.
- [ ] Ranking is deterministic for the same input.
- [ ] Match explanations are visible and traceable to underlying profile and job
      attributes.

## 6. Student Output

- [ ] The student weekly digest can be generated or demonstrated.
- [ ] The digest includes all matching opportunities in one ranked list.
- [ ] No separate "Top Matches" and "All Matches" sections appear.
- [ ] Each result includes the required job, match, and apply-link fields.
- [ ] If approved event data is available, associated employer events appear
      directly beneath the relevant job.
- [ ] Empty event sections are omitted.
- [ ] "Profile Used For Matching" appears at the bottom.
- [ ] Market statistics and GCS dashboard metrics are excluded.
- [ ] Output aligns with `docs/mvp_output_student_template.md`.

## 7. GCS Dashboard Output

- [ ] Job Market Overview metrics can be generated or demonstrated.
- [ ] Concentration Insights can be generated or demonstrated.
- [ ] OPT/CPT metrics count only explicitly friendly postings.
- [ ] Employer Activity includes source and retrieval context when available.
- [ ] Recruiting Events are shown only when approved event data is available.
- [ ] Unknown or unavailable metrics are labeled honestly.
- [ ] Dashboard metrics align with `docs/gcs_trend_outputs.md`.
- [ ] SQL drafts align with the dashboard sections.
- [ ] Output aligns with `docs/mvp_output_gcs_dashboard_template.md`.

## 8. Logging and Failures

- [ ] A successful run clearly reports completion and output location.
- [ ] Source-loading failures are logged or clearly surfaced.
- [ ] Validation failures identify the affected source or record.
- [ ] Empty input produces a clear failure rather than a misleading success.
- [ ] Unsupported source names produce a clear error.
- [ ] No credentials, student data, or sensitive values appear in logs.
- [ ] The demo has a prepared fallback using saved output if execution fails.

## 9. Known Limitations / Not MVP

- [ ] The presenter states that KelleyLink access depends on a future KSBIT
      Denodo view, endpoint, or scheduled export.
- [ ] The presenter states that Handshake is not confirmed for MVP job
      ingestion.
- [ ] LinkedIn scraping is not demonstrated or described as supported.
- [ ] Login automation, CAPTCHA bypassing, proxy rotation, and unapproved
      collection are not demonstrated.
- [ ] Student-level tracking is not presented as an MVP feature.
- [ ] Application, interview, and offer status tracking are not presented as
      MVP features.
- [ ] Alumni matching and recruiter recommendations are not presented as MVP
      features.
- [ ] Unconfirmed OPT/CPT, active-status, expiration, and retrieval fields are
      described as assumptions.
- [ ] Unsupported features are clearly labeled as future work.

## Final Sprint Review Check

- [ ] Run the automated test suite.
- [ ] Run the exact demo command once from a clean terminal.
- [ ] Open every file and output needed for the demo before presenting.
- [ ] Verify sample data contains no real student or sensitive information.
- [ ] Student output template and GCS dashboard template are consistent with
      current MVP assumptions.
- [ ] Confirm the demo can be completed within the allotted time.

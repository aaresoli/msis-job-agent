# Data Flow

Implemented local v0 flow:

1. Source registry verifies each source is approved to run.
2. Approved source adapter fetches local fixture/export job records.
3. Ingestion collects records from one or more adapters.
4. Normalization converts records into `JobPosting`.
5. Validation checks required fields and policy constraints.
6. Classification assigns role and concentration tags.
7. Deduplication removes repeated jobs by canonical URL or exact content match.
8. Ranking scores jobs for sample/student profiles.
9. Pipeline writes a local JSON report.
10. GCS helpers summarize program-level trend fields separately from ranking.
11. Evaluation reads labelled fixtures and reports classifier/ranking metrics.

Restricted sources such as LinkedIn and Handshake remain non-runnable until
official approval and compliant access methods exist.


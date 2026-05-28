# Data Flow

Planned high-level flow:

1. Approved source adapter fetches raw job records.
2. Ingestion collects records from one or more adapters.
3. Normalization converts records into `JobPosting`.
4. Validation checks required fields and policy constraints.
5. Deduplication removes repeated jobs, initially by URL.
6. Classification assigns concentration and role tags.
7. Ranking scores jobs for student profiles.
8. Agents prepare student matches or GCS summaries.
9. Delivery formats digest output.

This starter repository only implements safe local placeholders for those steps.


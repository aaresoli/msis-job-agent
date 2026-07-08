# Company Careers Source (`company_careers`)

The `company_careers` source fetches MSIS-relevant postings directly from
**public** employer career pages and **public** ATS job-board APIs, normalizes
them into the shared `JobPosting` model, filters/scores them for MSIS relevance,
deduplicates them, and feeds them into the same classification and ranking
pipeline used by KelleyLink/KSBIT.

## What it does

1. Reads a configurable company list (`config/company_careers.yml`).
2. For each enabled company, resolves the ATS provider adapter and fetches
   postings politely (rate limited, retried, timed out, clear User-Agent).
3. Runs a cheap, deterministic keyword relevance filter (no LLM) to drop
   clearly non-MSIS roles before doing any further work.
4. Normalizes retained postings into `JobPosting`, preserving the raw provider
   payload in `raw_metadata` for traceability.
5. Deduplicates and hands jobs to the existing classifier/ranker.
6. Produces a per-company health report (fetched/kept/skipped/errors).

## How it fits the source architecture

| Source | Access | Nature |
| --- | --- | --- |
| KelleyLink / KSBIT | Local export (JSON/CSV/XLSX) | Institutional, approved |
| Denodo (future) | KSBIT-provided API | Institutional, approved |
| **company_careers** | Public ATS APIs / public career pages | Autonomous, compliant |

All sources emit the same `JobPosting` shape and flow through the same
normalize → validate → dedupe → classify → rank pipeline. `company_careers`
runs **independently of Denodo**.

## Official MSIS concentrations

All outputs (tags, exports, docs, tests) use these exact names:

1. Data Analytics and AI
2. Cybersecurity and Risk Analytics
3. Digital Enterprise Systems and AI
4. Digital Platforms and Security
5. IS Research

### Old → new concentration alias map

Legacy/shorthand names are normalized to the official names by
`hope_job_agent.classification.taxonomy.normalize_concentration`. Final outputs
never use the outdated names.

| Legacy / shorthand | Official name |
| --- | --- |
| Business Intelligence and Analytics, Analytics, Data Analytics, AI, DAAI | Data Analytics and AI |
| Cybersecurity, Security, Risk Analytics, CRA | Cybersecurity and Risk Analytics |
| Enterprise Systems, Digital Enterprise Systems, DESAI, ERP, SAP, Enterprise AI | Digital Enterprise Systems and AI |
| Digital Platforms, Cloud Platforms, Technology Architecture, Platform Security, DPS | Digital Platforms and Security |
| IS Research, ISR, Pre-PhD, Research | IS Research |

## How to add or disable a company

Edit `config/company_careers.yml`. Each entry:

```yaml
- company_name: "Example Corp"
  ats_provider: greenhouse          # greenhouse | lever | ashby | smartrecruiters | workday | oraclecloud | icims | static
  ats_slug: examplecorp             # board token / site / board name / company id
  # Workday only:
  # host: example.wd1.myworkdayjobs.com
  # tenant: example
  # site: External
  careers_url: "https://example.com/careers"
  enabled: true
  priority: 20                      # lower = fetched earlier
  country_filters: []               # e.g. ["United States", "us"]
  location_filters: []              # e.g. ["Indianapolis", "Chicago", "Remote"]
  workplace_filters: []             # e.g. ["remote", "hybrid"]
  relevant_keywords_override: null  # optional list of extra keywords to boost
  notes: "Why this company is relevant."
  compliance_review: "How the public endpoint was verified."
  # LAMP tracked-company coverage metadata — set by the verification workflow:
  student_interest_rank: 12         # rank in the MSIS LAMP list (1-300; omit if not tracked)
  merged_excel_ranks: []            # Excel ranks merged into this entry as duplicate aliases
  student_interest_count: 59        # "Student Interest #" from the Excel
  industry: "Management Consulting"
  verification_status: verified     # verified | pending | unsupported
  verified_at: "2026-07-08"
  verification_source_url: "https://..."  # the endpoint probed at verification
  unsupported_reason: null          # required when verification_status: unsupported
```

Rules enforced by config validation: a company with `student_interest_rank`
set may only be `enabled: true` when `verification_status: verified`, and
`unsupported` entries must carry an `unsupported_reason`.

To find the ATS identifier:

- **Greenhouse**: the board token in `boards-api.greenhouse.io/v1/boards/<TOKEN>/jobs`.
- **Lever**: the site in `api.lever.co/v0/postings/<SITE>`.
- **Ashby**: the job-board name in `api.ashbyhq.com/posting-api/job-board/<NAME>`.
- **SmartRecruiters**: the company id in `api.smartrecruiters.com/v1/companies/<ID>/postings`.
- **Workday**: `host`, `tenant`, and `site` from the company's `*.myworkdayjobs.com`
  career site. Verify one at a time and keep request volume low. Note the tenant
  can differ from the host prefix (e.g. RSM: host `rsmus.wd1...`, tenant `rsm`).
- **Oracle Recruiting Cloud**: `host` (the `*.fa.*.oraclecloud.com` Fusion host)
  and `site` (the `CX_*` Candidate Experience site number) from the company's
  public career-site URLs, e.g.
  `https://<host>/hcmUI/CandidateExperience/en/sites/<CX_site>/job/<id>`.

To verify coverage of the ranked MSIS LAMP list (all 300 ranks by default), run:

```bash
python scripts/research_lamp_companies.py --live   # low-volume endpoint probes
```

which writes `outputs/company_coverage_report.{json,md}`. Without `--live` it
only diffs the Excel ranked list against the config (no network access).

## Operations: refreshing and health

Run monthly (or before a demo):

```bash
# 1. Endpoint refresh: ONE small request per enabled company; flags drift.
#    Never edits config — review outputs/ats_refresh_report.md first.
python scripts/ats_refresh_endpoints.py

# 2. Coverage research: full discovery + verification against the Excel list
#    (use --only NAME to re-discover a single drifted company).
python scripts/research_lamp_companies.py --live

# 3. Bounded ingestion smoke (title-only relevance, 50 jobs/company).
python -m hope_job_agent.pipeline.run_mvp --source company_careers \
    --output outputs/smoke/company_careers_jobs.csv --skip-store

# 4. Health report (Markdown + JSON): config + coverage + last run summary.
python scripts/ats_health_report.py \
    --run-summary outputs/smoke/company_careers_jobs.summary.json

# 5. Quality audit (Markdown + JSON): samples and false-positive heuristics.
python scripts/ats_quality_audit.py \
    --jobs outputs/smoke/company_careers_jobs.csv \
    --run-summary outputs/smoke/company_careers_jobs.summary.json

# 6. Combined-source smoke with a local export (KSBIT sample shown).
python -m hope_job_agent.pipeline.run_mvp --source all \
    --local-source ksbit_export --input data/sample_ksbit_jobs.json \
    --output outputs/smoke/all_results.csv --skip-store
```

Rank coverage counts **ranks, not entries**: duplicate Excel aliases merge
into the best-ranked canonical entry, which lists the absorbed ranks in
`merged_excel_ranks` (109 "Slalom Consulting" -> 93 "Slalom", 110 "TCS" -> 78
"Tata Consultancy Services", 235 "Eli Lilly and Company" -> 16, 247 "Hewlett
Packard Enterprise (HPE)" -> 142), so 296 entries account for all 300 ranks.
Brands that hire through an already-enabled parent board (e.g. Tableau ->
Salesforce, Cerner -> Oracle, Chevrolet -> GM, Discover -> Capital One) stay
disabled with a covered-by reason so a shared endpoint is never fetched
twice. `unsupported` and `pending` are intentional compliance outcomes —
documented decisions, not failures.

How to interpret failures in the health output:

- **blocked / 401 / 403**: the ATS refuses unauthenticated or generic-UA
  requests. Per compliance rules, disable the company (set
  `verification_status: unsupported` with the reason) — do not retry harder.
- **robots_disallowed**: the endpoint host's robots.txt forbids generic
  crawlers (currently all of `api.smartrecruiters.com`). The runtime skips
  these automatically; enabling them is a GCS policy decision.
- **failed with 5xx** (e.g. the FIS Global HTTP 520 seen 2026-07-08): usually
  transient; re-run before demoting the company.
- **404 / 410 / 422 on Workday cxs**: the tenant/site id changed. Mark the
  entry `pending`, re-discover the site id from the public career page, and
  re-verify before re-enabling.
- **empty**: endpoint healthy but zero postings — normal for small boards.
- **zero kept**: postings fetched but none passed relevance. Expected
  occasionally for hardware/airline/retail-heavy boards, and more common in
  smoke runs with `fetch_descriptions: false` (title-only scoring). Only tune
  keywords when a manual sample shows real MSIS roles being dropped.
- **stale verified_at**: older than the `--stale-days` window (default 30);
  re-run step 1 to refresh the dates.

Unsupported employers stay in the config (`enabled: false`,
`unsupported_reason`) so every compliance decision remains visible and
auditable rather than silently dropped.

**To disable** a company, set `enabled: false`. Leave a `notes`/`compliance_review`
explaining why (e.g. no compliant public endpoint yet). iCIMS-backed companies
must stay disabled until an approved partner API/export exists.

## How to run it locally

Run company_careers only (jobs-only mode, no student profiles):

```bash
python -m hope_job_agent.pipeline.run_mvp \
  --source company_careers \
  --limit 200 --dry-run
```

Run company_careers and write outputs (jobs + data-quality + GCS trends + summary):

```bash
python -m hope_job_agent.pipeline.run_mvp \
  --source company_careers \
  --company-config config/company_careers.yml \
  --output outputs/company_careers/results.json \
  --skip-store
```

Run the KelleyLink/KSBIT spreadsheet only (unchanged):

```bash
python -m hope_job_agent.pipeline.run_mvp \
  --source kelleylink_excel \
  --input data/sample_ksbit_jobs.json \
  --output outputs/kelleylink/results.json --skip-store
```

Run all enabled sources (company_careers + a local export):

```bash
python -m hope_job_agent.pipeline.run_mvp \
  --source all \
  --local-source kelleylink_excel \
  --input data/sample_ksbit_jobs.json \
  --output outputs/all/results.json --skip-store
```

(`--source all` without `--input` runs company_careers only.)

## How to run tests

```bash
python -m pytest tests/sources/company_careers -q          # this source
python -m pytest tests/test_concentration_aliases.py -q    # concentration migration
python -m pytest -q                                        # everything
```

Tests use mocked HTTP responses (`FakeTransport`) and never touch a live
career site.

## Interpreting the source health output

The run summary includes `company_careers_health` and the CLI prints a
per-company breakdown:

```
Company careers: fetched=40 kept=2 duplicates=0 ok=1/1
  - Stripe [greenhouse]: status=ok fetched=40 kept=2 skipped_kw=38 skipped_filter=0
```

Per-company fields: `status` (`ok` / `empty` / `failed` / `blocked` /
`robots_disallowed` / `not_implemented`), `fetched`, `kept`,
`skipped_by_keyword`, `skipped_by_filter`, `invalid`, `error`, `last_fetch_at`.
Run-level fields: `raw_count`, `kept_count`, `duplicate_count`,
`companies_ok`/`companies_total`, and `failed_companies`.

## How relevance scoring works

`relevance.py` scores each posting deterministically (see `score_relevance`):

- **+3** strong title match (e.g. business/data/security/systems analyst,
  solutions engineer, SAP consultant, cloud solutions analyst).
- **+2** official concentration keyword in title/description.
- **+2** early-career indicator (intern, new grad, associate, rotational, ...).
- **+1** tools/skills (SQL, Python, Tableau, Power BI, Snowflake, AWS, Azure,
  SAP, Salesforce, Workday, ServiceNow, ...).
- **+1** broad relevant signal (consulting, transformation, implementation,
  platform, analytics, cloud, security, risk, AI, data, ...).
- **+1** optional per-company `relevant_keywords_override` hit.
- **−3** senior/leadership title (senior/director/principal/staff/VP/executive)
  — applied to the **title**, not description sentences.
- **−4** clearly unrelated domain (nurse, warehouse, driver, mechanical
  engineer, ...) — applied to the **title**.

A posting is retained when `score >= relevance_threshold` (default `3`). The
score, matched keywords, career stage, and reasons are stored in
`raw_metadata.msis_relevance` and on the `relevance_score` / `matched_keywords`
/ `career_stage` fields.

## How concentration classification works

Relevance produces **concentration hints** (official names) that are stored in
`raw_metadata`. The final `concentration_tags` are assigned by the existing
deterministic classifier (`hope_job_agent.classification.classifier`), which
only ever emits the five official concentration names. IS Research is available
for research/academic/PhD-prep postings but does not dominate ordinary
company-career matches (its keyword family is intentionally academic).

## Compliance notes (what NOT to do)

- Public pages / public ATS APIs only.
- No login-gated scraping. No LinkedIn/Handshake collection.
- No CAPTCHA bypass, no proxy evasion, no anti-bot circumvention.
- Respect `robots.txt` and rate limits.
- Stop fetching a source if it blocks the crawler or disallows automated access
  (the adapter does this automatically and reports it).
- Never commit API keys or credentials (none are required for these public
  endpoints).

# company_careers source

Fetches MSIS-relevant job postings directly from **public** employer career
pages and **public** ATS job-board APIs, normalizes them into the shared
`JobPosting` model, filters/scores them for MSIS relevance, deduplicates them,
and feeds them into the same downstream classification and ranking pipeline as
the KelleyLink/KSBIT local-export source.

This is a compliant, configurable source adapter — not a generic scraper.

## Why it is separate from KelleyLink/KSBIT/Denodo

- **KelleyLink/KSBIT** is a local export (JSON/CSV/XLSX) of Kelley-approved
  postings. **Denodo** is a future KSBIT-provided API. Both are institutional.
- **company_careers** pulls from employers' own public ATS boards. It is
  autonomous (runs without manual export/Denodo) and complements the other
  sources so MSIS students see real, current postings across all five
  concentrations.
- All sources emit the same `JobPosting` shape and flow through the same
  normalize → validate → dedupe → classify → rank pipeline.

## Module layout

| File | Purpose |
| --- | --- |
| `adapter.py` | `CompanyCareersSource` orchestration + `fetch_all_jobs()` + per-company health report |
| `config.py` | Pydantic config models + YAML/JSON loader |
| `relevance.py` | Deterministic keyword relevance filter/scoring + career-stage detection |
| `http.py` | Polite stdlib HTTP client (rate limit, retries/backoff, timeout, User-Agent) |
| `robots.py` | robots.txt policy checks |
| `registry.py` | Maps ATS provider name → adapter |
| `providers/` | One small, testable adapter per ATS (greenhouse, lever, ashby, smartrecruiters, workday, icims) |

## Providers implemented

| Provider | Endpoint style | Status |
| --- | --- | --- |
| Greenhouse | `boards-api.greenhouse.io/v1/boards/{token}/jobs?content=true` | Implemented |
| Lever | `api.lever.co/v0/postings/{site}?mode=json` | Implemented |
| Ashby | `api.ashbyhq.com/posting-api/job-board/{board}` | Implemented |
| SmartRecruiters | `api.smartrecruiters.com/v1/companies/{id}/postings` (+ detail) | Implemented |
| Workday | `{host}/wday/cxs/{tenant}/{site}/jobs` (POST, + detail) | Implemented (enable per verified tenant) |
| iCIMS | — | Interface only; no clean public JSON board. Keep companies disabled. |

## Compliance (must-read)

- Public employer career pages and public ATS APIs only.
- **No** LinkedIn/Handshake or any logged-in / account-gated collection.
- **No** CAPTCHA solving, login automation, proxy evasion, or access-control
  bypass.
- Respect `robots.txt` (where applicable), rate limit, send a clear
  `User-Agent`, and log fetch activity.
- If a source returns 401/403/407/451, it is treated as blocking the crawler:
  the run stops fetching that source and marks it failed/blocked.
- Raw provider payloads are stored in `raw_metadata.provider_payload` for
  traceability.

See `docs/company_careers.md` for how to add/disable a company, run locally,
run tests, interpret the health report, and how relevance scoring and
concentration classification work.

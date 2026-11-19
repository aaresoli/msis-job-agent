# Compliance Notes

The project must use only approved and compliant data access methods.

## Prohibited Work

- Unauthorized scraping
- Login scraping
- CAPTCHA bypassing
- Proxy rotation to avoid rate limits or access controls
- LinkedIn scraping
- Collection of private data without approval

## Required Before Adding a Source

- Confirm the source is approved for the project.
- Review the source terms of service and API documentation.
- Document the approved access method.
- Avoid storing credentials in the repository.
- Add tests that use mock data, not live restricted systems.
- Add the source to `hope_job_agent.sources.registry` with an approval status.
- Ensure the pipeline refuses restricted or disabled sources by default.

## LinkedIn

LinkedIn access must use approved and compliant methods only. This repository includes a placeholder module for future reference workflows, but it does not implement LinkedIn data collection.

## Handshake

Handshake access requires official access/API approval before implementation. This repository includes only a placeholder stub.

## Company Careers (public ATS boards)

The `company_careers` source collects postings from **public** employer career
pages and **public** ATS job-board APIs (Greenhouse, Lever, Ashby,
SmartRecruiters, Workday). It is compliant by construction:

- Public endpoints only; no login-gated or account-gated collection.
- No LinkedIn/Handshake collection.
- No CAPTCHA solving, login automation, proxy evasion, or access-control bypass.
- Respects `robots.txt` (where applicable), rate limits, sends a clear
  `User-Agent`, and logs fetch activity.
- Treats HTTP 401/403/407/451 as the source blocking the crawler: it stops
  fetching that source and marks it failed/blocked.
- Stores raw provider payloads in `raw_metadata` for traceability.
- Company list is configurable in `config/company_careers.yml`; brittle or
  unsupported employers are left `enabled: false` rather than shipping flaky
  collection. See `docs/company_careers.md`.

## Current Registry

- `approved_json`: approved local export fixture.
- `employer_careers`: approved realistic local fixture.
- `company_careers`: approved public ATS/career-page source (see above).
- `ksbit_export`: approved local JSON/CSV/XLSX export adapter for
  KSBIT-compatible and 12Twenty/KelleyLink exports. It preserves source-row
  context for auditability, excludes applicant/application analytics fields
  from raw metadata, and does not use credentials or live collection.
- `handshake`: restricted; blocked at runtime.
- `linkedin_reference`: manual reference only; blocked at runtime.

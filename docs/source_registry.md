# Source Registry and Compliance Guardrails

This registry documents the approval status and permitted access method for
job sources considered by the HOPE MSIS Job Agent. A source must use an
approved access method before it can be enabled in the ingestion pipeline.

## Source Registry

| source_name | source_type | allowed_status | access_method | rate_limit | TOS_risk | notes |
| --- | --- | --- | --- | --- | --- | --- |
| approved_json | Local JSON export | Approved | Read an approved local JSON export | Not applicable | Low | Current Sprint 2 source |
| employer_careers | Local sample source | Approved | Read local sample employer-career data | Not applicable | Low | Sprint 2 prototype |
| KelleyLink / 12Twenty | Internal career platform | Approved candidate | Internal API endpoint through KSBIT | Follow KSBIT and API-defined limits | Low | Existing API access and daily job posting downloads |
| Handshake | Career services platform | Pending review | KSBIT API endpoint or nightly report processing | Follow KSBIT or report-delivery limits | Medium | Direct Handshake API access not currently available |
| Greenhouse | Public ATS API | Approved candidate | Public ATS API | Follow published API limits | Low | Enable only through the documented public API |
| Lever | Public ATS Job Postings API | Approved candidate | Public ATS Job Postings API | Follow published API limits | Low | Enable only through the documented public API |
| Ashby | Public ATS endpoint | Approved candidate | Public ATS endpoint | Follow published endpoint limits | Low | Enable only through the documented public endpoint |
| Workday | Company career sites | Pending review - for future review | No access method approved yet | Not applicable until approved | Medium | Do not collect until an approved access method is documented |
| LinkedIn | Professional network | Not approved | No collection allowed | Not applicable | High | No scraping allowed |

## Compliance Guardrails

- No restricted scraping.
- No login automation.
- No CAPTCHA bypassing.
- No proxy rotation.
- Use approved APIs, exports, public endpoints, or KSBIT endpoints only.
- Log source name and retrieval date.
- Mark unapproved sources as pending review.
- Respect source rate limits.
- Follow source terms of service.

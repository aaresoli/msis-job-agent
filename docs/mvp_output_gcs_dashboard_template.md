# MVP Output GCS Dashboard Template

## 1. Purpose

The HOPE MVP GCS dashboard gives Graduate Career Services an on-demand view of
current job opportunities, employer activity, concentration trends, OPT/CPT
opportunities, and recruiting events. Unlike the student-facing weekly email,
this output is a dashboard that GCS can access whenever needed.

The dashboard supports career coaching conversations about role options,
industries, locations, employer demand, and international-student eligibility.
It is designed to reduce manual trend gathering and help GCS guide students who
are overwhelmed by career-path choices or struggling to find open positions.

## 2. MVP GCS Dashboard Overview

The MVP dashboard uses approved, normalized, and deduplicated job and event
data. It emphasizes current opportunities and aggregate recruiting trends.

Primary users:

- GCS career coaches and advisors
- GCS staff monitoring employer and recruiting activity
- Program stakeholders reviewing concentration-level opportunity trends

The dashboard is refreshed according to the approved source retrieval schedule
and shows the last retrieval date so users can judge data freshness.

## 3. Dashboard Sections

### A. Job Market Overview

- Total active postings
- New postings this week
- Unique employers
- Top employers
- Top locations
- Top role categories

### B. Concentration Insights

For each MSIS concentration:

- Concentration name
- Posting count
- Top roles
- Top employers
- Top locations

### C. OPT/CPT Opportunities

- Total OPT/CPT-friendly postings
- New OPT/CPT-friendly postings this week
- Top employers with OPT/CPT-friendly roles
- Top locations for OPT/CPT-friendly roles

### D. Employer Activity

- Employer name
- Posting count
- Recent roles posted
- Source
- Last retrieved date

### E. Recruiting Events

- Employer name
- Event name
- Event type
- Event date
- Related concentration or role area, if available

## 4. Fields Shown

| Dashboard field | Purpose |
| --- | --- |
| Active posting count | Shows current opportunity volume |
| New posting count | Shows postings added during the current week |
| Company/employer | Supports employer activity and trend reporting |
| Job title | Identifies recent roles and supports role classification |
| Role category | Groups opportunities into career-path areas |
| Concentration tag | Connects opportunities to MSIS concentrations |
| Location | Supports geographic and remote-work trends |
| Source | Identifies the approved source that supplied the record |
| Posted date | Supports recency and weekly trend calculations |
| Last retrieved date | Shows when the source record was last collected |
| OPT/CPT-friendly flag | Identifies approved eligibility information |
| Event name | Identifies a recruiting or employer event |
| Event type | Distinguishes fairs, sessions, presentations, and other events |
| Event date | Supports upcoming-event reporting |
| Related role/concentration | Connects events to relevant career areas |

## 5. Sample Dashboard Layout

```text
HOPE GCS JOB MARKET DASHBOARD
Data last retrieved: September 10, 2026

JOB MARKET OVERVIEW
Active postings:        486
New this week:           64
Unique employers:       173

Top employers
1. Cummins                         18 postings
2. Eli Lilly                       15 postings
3. Deloitte                        13 postings
4. Salesforce                      11 postings
5. IU Health                        9 postings

Top locations
1. Indianapolis, IN                92 postings
2. Chicago, IL                     67 postings
3. Remote                          54 postings
4. Columbus, IN                    31 postings
5. Cincinnati, OH                 24 postings

Top role categories
1. Data and Analytics             126 postings
2. IT Strategy and Consulting      94 postings
3. Enterprise Systems              83 postings
4. Cybersecurity                   71 postings
5. Digital Enterprise Systems      58 postings

CONCENTRATION INSIGHTS
Business Analytics
Posting count: 126
Top roles: Data Analyst, BI Analyst, Analytics Consultant
Top employers: Cummins, Eli Lilly, Deloitte
Top locations: Indianapolis, Chicago, Remote

Cybersecurity
Posting count: 71
Top roles: Security Analyst, Risk Analyst, Security Consultant
Top employers: PwC, Crowe, Salesforce
Top locations: Chicago, Indianapolis, Remote

OPT/CPT OPPORTUNITIES
OPT/CPT-friendly postings:          84
New this week:                      12
Top employers: Cummins, Deloitte, IU Health
Top locations: Indianapolis, Chicago, Remote

EMPLOYER ACTIVITY
Employer       Postings  Recent roles                 Source       Retrieved
Cummins        18        Data Analyst, IT Consultant  KelleyLink   Sep 10, 2026
Eli Lilly      15        BI Analyst, Systems Analyst  KelleyLink   Sep 10, 2026
Deloitte       13        Technology Consultant        approved_json Sep 9, 2026

RECRUITING EVENTS
Employer  Event                         Type                 Date
Cummins   Cummins Information Session   Information Session  Sep 12, 2026
Deloitte  Technology Consulting Night   Recruiting Event     Sep 18, 2026

Related areas
Cummins: Business Analytics, Enterprise Systems
Deloitte: IT Strategy and Consulting
```

## 6. MVP Data Supported

- Approved-source job postings
- Aggregate posting and employer counts
- Posting dates and retrieval dates
- Job titles, role categories, and concentration classifications
- Job locations and remote status when available
- OPT/CPT-friendly indicators when explicitly supplied by an approved source
- Employer recruiting events from approved event data
- Source-level traceability

## 7. Future Enhancements / Not MVP

The following may support GCS's longer-term goals but are not MVP features:

- Student-level tracking
- Individual student progress
- Application status
- Interview status
- Offer tracking
- Alumni matching or alumni-database connections
- Recruiter contact recommendations
- Personalized advisor workflow alerts
- Student career-journey histories
- AI-generated alumni or recruiter introductions

These capabilities require approved data sources, privacy review, access
controls, retention rules, and confirmation that student-, applicant-, alumni-,
or recruiter-level data may be used.

## 8. Notes and Assumptions

- The dashboard is available on demand; it is not an email digest.
- Metrics use normalized and deduplicated records from approved sources only.
- "Active" depends on an approved expiration or status field. Until one is
  available, the MVP may use a documented posting-age window.
- "New this week" should use `posted_date` when reliable and otherwise use the
  approved retrieval date.
- OPT/CPT status must not be inferred when an approved source does not provide
  it; unknown values should remain unknown.
- Event-to-employer matching requires a stable employer identifier or a
  documented company-name normalization method.
- Handshake, LinkedIn, KelleyLink, recruiter requests, alumni connections, and
  historical GCS knowledge may inform long-term trend analysis only through
  approved access methods.
- Student-level career journey data is excluded from the MVP unless explicitly
  approved.

# MVP Output Student Template

## 1. Purpose

The HOPE MVP student output is a weekly email digest designed to help students
identify and act on relevant opportunities. It presents all matching jobs in
one ranked list and emphasizes clear match context, upcoming employer events,
and direct application links.

The student digest is not a labor-market analytics report or dashboard. It
does not include market statistics, skill trends, concentration market-share
charts, or employer-count metrics.

## 2. Student Weekly Email Template

```text
Subject: HOPE Weekly Job Digest

HOPE Weekly Job Digest

Hi [Student Name],

[Match Count] opportunities matched your profile this week.

1. [Job Title]
   [Company] | [Location]
   Source: [Source]
   Posted: [Posted Date]
   Match: [Excellent Match | Strong Match | Good Match]
   Role Category: [Role Category]
   Concentration Fit: [Concentration Fit]
   OPT/CPT Friendly: [Yes | No | Unknown]
   Why This Matched: [Short explanation]
   Apply: [Apply Link]

   Upcoming Event:
   [Event Name]
   [Event Date]
   [Event Location]

2. [Job Title]
   [Company] | [Location]
   Source: [Source]
   Posted: [Posted Date]
   Match: [Excellent Match | Strong Match | Good Match]
   Role Category: [Role Category]
   Concentration Fit: [Concentration Fit]
   OPT/CPT Friendly: [Yes | No | Unknown]
   Why This Matched: [Short explanation]
   Apply: [Apply Link]

[Continue until every matching opportunity has been displayed.]

Profile Used For Matching

Concentration: [Concentration]
Target Roles: [Target Roles]
Location Preference: [Location Preference]
Work Authorization: [Work Authorization]
```

All matching opportunities appear in this single ranked list. The email must
not split results into separate sections such as "Top Matches" and "All
Matches."

## 3. Fields Included in Each Job Result

| Field | Description |
| --- | --- |
| Job Title | Title of the opportunity |
| Company | Employer offering the opportunity |
| Location | Job location or remote status |
| Source | Approved source that supplied the posting |
| Posted Date | Source-reported posting date |
| Match Label | `Excellent Match`, `Strong Match`, or `Good Match` |
| Role Category | Classified role family for the posting |
| Concentration Fit | Student concentration aligned with the posting |
| OPT/CPT Friendly Flag | `Yes`, `No`, or `Unknown` |
| Why This Matched | Short explanation of the strongest matching factors |
| Apply Link | Direct URL for viewing or applying to the opportunity |

## 4. Sorting Logic

Jobs appear in a single ranked list using this priority order:

1. OPT/CPT-friendly postings first when the student requires OPT/CPT
   sponsorship.
2. Match strength, ordered from `Excellent Match` to `Strong Match` to `Good
   Match`.
3. Most recent posting date first.

When a student does not require OPT/CPT sponsorship, match strength becomes the
first sorting criterion. Stable tie-breaking may use company and job title in
alphabetical order.

## 5. Event Matching Logic

When an employer event is associated with a company in the recommended jobs
list, display the event directly beneath that company's job result. Applicable
events include:

- Employer events
- Information sessions
- Career fairs
- Networking events
- Recruiting events
- Employer presentations

Example:

```text
Upcoming Event:
Cummins Information Session
September 12, 2026
Kelley School of Business
```

If no associated event is available, omit the event section entirely. Do not
display an empty event heading or placeholder.

## 6. Sample Student Email

```text
Subject: HOPE Weekly Job Digest

HOPE Weekly Job Digest

Hi [Student Name],

18 opportunities matched your profile this week.

1. Data Analytics Consultant
   Cummins | Columbus, IN
   Source: KelleyLink
   Posted: September 8, 2026
   Match: Excellent Match
   Role Category: Data Analyst / BI Engineer
   Concentration Fit: Data Analytics and AI
   OPT/CPT Friendly: Yes
   Why This Matched: Matches your analytics concentration, SQL skills, and
   consulting target role.
   Apply: https://example.com/jobs/data-analytics-consultant

   Upcoming Event:
   Cummins Information Session
   September 12, 2026
   Kelley School of Business

2. Technology Strategy Analyst
   Example Advisory Group | Chicago, IL
   Source: approved_json
   Posted: September 6, 2026
   Match: Strong Match
   Role Category: IT Consultant / Tech Risk
   Concentration Fit: Digital Transformation with AI
   OPT/CPT Friendly: Yes
   Why This Matched: Aligns with your target strategy roles and technology
   consulting interests.
   Apply: https://example.com/jobs/technology-strategy-analyst

3. ERP Systems Analyst
   Example Manufacturing | Indianapolis, IN
   Source: employer_careers
   Posted: September 4, 2026
   Match: Good Match
   Role Category: IT Consultant / Tech Risk
   Concentration Fit: Digital Transformation with AI
   OPT/CPT Friendly: Unknown
   Why This Matched: Matches your ERP interest and preferred Indiana location.
   Apply: https://example.com/jobs/enterprise-systems-analyst

[Jobs 4 through 18 continue in the same ranked format.]

Profile Used For Matching

Concentration: Data Analytics and AI
Target Roles: Data Analyst, Analytics Consultant, Technology Consultant
Location Preference: Indiana, Chicago, or Remote
Work Authorization: OPT/CPT sponsorship required
```

## 7. Notes and Assumptions

- The MVP output is delivered as a weekly email digest.
- The digest lists all matching opportunities in one ranked list.
- Match-label thresholds must be documented alongside the ranking logic before
  production use.
- `Unknown` should be used when OPT/CPT status or posting date is unavailable;
  the system must not infer sponsorship support without approved data.
- Event matching depends on an approved event source and a reliable employer
  identifier or normalized company name.
- The MVP does not include a "Top Matches" section.
- The MVP does not include market statistics, skill-trend dashboards,
  concentration market-share charts, or employer-count metrics.
- Alumni information is not included unless an approved data source becomes
  available.
- Recruiter contact information is not included unless an approved data source
  becomes available.
- Application tracking is not included unless an approved data source becomes
  available.
- Employer response status is not included unless an approved data source
  becomes available.
- Interview status tracking is not included unless an approved data source
  becomes available.

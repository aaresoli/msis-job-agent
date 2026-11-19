"""Generate a committed, schema-faithful synthetic 12Twenty/KelleyLink export.

The real KelleyLink export contains student PII and cannot be committed. This
script writes a synthetic `.xlsx` that mirrors the real 12Twenty dry-run column
layout (JSON location cells, status values, work-authorization strings, and the
sensitive analytics columns the adapter must exclude) using entirely fabricated
data, so the Excel path can be exercised deterministically in tests.

Run: python scripts/generate_sample_12twenty_xlsx.py
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

from openpyxl import Workbook

OUTPUT_PATH = Path("data/sample_12twenty_export.xlsx")

# Mirrors the real 12Twenty dry-run header layout, including sensitive analytics
# columns that the adapter is required to drop.
HEADERS = [
    "Job Posting ID",
    "Job Title",
    "Company Name",
    "Status",
    "Posted Date",
    "Job Description",
    "Application URL",
    "Location",
    "Location Type",
    "Job Type",
    "Work Authorization Requirement",
    "Application Count",
    "Distinct Applicant Count",
]


def _location(city_state: str) -> str:
    city = city_state
    return '{"Rank":0,"CountryName":"United States (USA)",' f'"CityName":"{city}"}}'


ROWS: list[dict[str, object]] = [
    {
        "Job Posting ID": "12t-0001",
        "Job Title": "Data Analyst Intern",
        "Company Name": "Cardinal Analytics",
        "Status": "Application Open",
        "Posted Date": datetime(2026, 6, 20, 8, 15, 0),
        "Job Description": (
            "<p>Analyze customer and operations data with SQL, Python, Tableau, "
            "and Power BI dashboards to support business stakeholders.</p>"
        ),
        "Application URL": "https://careers.example.com/cardinal/data-analyst-intern",
        "Location": _location("Bloomington - IN"),
        "Location Type": "Specify Location(s)",
        "Job Type": "Internship",
        "Work Authorization Requirement": "All Work Authorizations Accepted",
        "Application Count": 14,
        "Distinct Applicant Count": 11,
    },
    {
        "Job Posting ID": "12t-0002",
        "Job Title": "Cybersecurity Analyst Intern",
        "Company Name": "Monroe Security Labs",
        "Status": "Application Open",
        "Posted Date": datetime(2026, 6, 18, 9, 30, 0),
        "Job Description": (
            "<p>Investigate SIEM alerts, map NIST controls, triage "
            "vulnerabilities, and document security risk findings.</p>"
        ),
        "Application URL": "https://careers.example.com/monroe/cybersecurity-analyst",
        "Location": _location("Indianapolis - IN"),
        "Location Type": "Specify Location(s)",
        "Job Type": "Internship",
        "Work Authorization Requirement": "US Citizens and Permanent Residents Only",
        "Application Count": 8,
        "Distinct Applicant Count": 7,
    },
    {
        "Job Posting ID": "12t-0003",
        "Job Title": "Platform Security Engineer Intern",
        "Company Name": "Meridian Cloud Platforms",
        "Status": "Application Open",
        "Posted Date": datetime(2026, 6, 15, 12, 0, 0),
        "Job Description": (
            "<p>Support secure cloud platform engineering with IAM, zero trust "
            "access, DevSecOps pipelines, Kubernetes hardening, and API "
            "security reviews.</p>"
        ),
        "Application URL": "https://careers.example.com/meridian/platform-security",
        "Location": _location("Chicago - IL"),
        "Location Type": "Specify Location(s)",
        "Job Type": "Internship",
        "Work Authorization Requirement": "All Work Authorizations Accepted",
        "Application Count": 5,
        "Distinct Applicant Count": 5,
    },
    {
        "Job Posting ID": "12t-0004",
        "Job Title": "ERP Systems Consultant",
        "Company Name": "Northstar Advisory",
        "Status": "Application Open",
        "Posted Date": datetime(2026, 6, 10, 7, 45, 0),
        "Job Description": (
            "<p>Improve ERP workflows, reporting, and enterprise automation, and "
            "manage agile delivery for client digital transformation programs.</p>"
        ),
        "Application URL": "https://careers.example.com/northstar/erp-consultant",
        "Location": _location("Cincinnati - OH"),
        "Location Type": "Specify Location(s)",
        "Job Type": "Full-Time",
        "Work Authorization Requirement": "All Work Authorizations Accepted",
        "Application Count": 3,
        "Distinct Applicant Count": 3,
    },
    {
        "Job Posting ID": "12t-0005",
        "Job Title": "AI Research Assistant",
        "Company Name": "Beacon Research Institute",
        "Status": "Application Open",
        "Posted Date": datetime(2026, 6, 8, 10, 0, 0),
        "Job Description": (
            "<p>Conduct AI research, NLP experiments, literature review, and "
            "statistical modeling with machine learning methods.</p>"
        ),
        "Application URL": "https://careers.example.com/beacon/ai-research-assistant",
        "Location": "",
        "Location Type": "Remote",
        "Job Type": "Full-Time",
        "Work Authorization Requirement": "All Work Authorizations Accepted",
        "Application Count": 0,
        "Distinct Applicant Count": 0,
    },
    {
        # Closed postings must be filtered out by the adapter status filter.
        "Job Posting ID": "12t-0006",
        "Job Title": "Expired Business Analyst",
        "Company Name": "Lakeview Retail Systems",
        "Status": "Application Closed",
        "Posted Date": datetime(2026, 5, 1, 9, 0, 0),
        "Job Description": "<p>This posting is closed and should be skipped.</p>",
        "Application URL": "https://careers.example.com/lakeview/expired-analyst",
        "Location": _location("Chicago - IL"),
        "Location Type": "Specify Location(s)",
        "Job Type": "Full-Time",
        "Work Authorization Requirement": "All Work Authorizations Accepted",
        "Application Count": 20,
        "Distinct Applicant Count": 18,
    },
    {
        # Missing Application URL must be skipped with a warning.
        "Job Posting ID": "12t-0007",
        "Job Title": "Analyst Without URL",
        "Company Name": "Redbud Insights",
        "Status": "Application Open",
        "Posted Date": datetime(2026, 6, 5, 9, 0, 0),
        "Job Description": "<p>Analyze engagement data with SQL and Python.</p>",
        "Application URL": "",
        "Location": _location("Bloomington - IN"),
        "Location Type": "Specify Location(s)",
        "Job Type": "Internship",
        "Work Authorization Requirement": "All Work Authorizations Accepted",
        "Application Count": 1,
        "Distinct Applicant Count": 1,
    },
    {
        # Missing Job Posting ID exercises the fallback id generation path.
        "Job Posting ID": "",
        "Job Title": "Data Engineering Associate",
        "Company Name": "Sample Data Works",
        "Status": "Application Open",
        "Posted Date": datetime(2026, 6, 3, 9, 0, 0),
        "Job Description": (
            "<p>Build Python data pipelines, SQL transformations, and "
            "analytics-ready warehouse tables.</p>"
        ),
        "Application URL": "https://careers.example.com/sampledata/data-engineering",
        "Location": _location("Remote - Remote"),
        "Location Type": "Specify Location(s)",
        "Job Type": "Full-Time",
        "Work Authorization Requirement": "All Work Authorizations Accepted",
        "Application Count": 2,
        "Distinct Applicant Count": 2,
    },
]


def generate(output_path: Path = OUTPUT_PATH) -> Path:
    """Write the synthetic 12Twenty export workbook and return its path."""

    workbook = Workbook()
    worksheet = workbook.active
    worksheet.title = "Job Postings"
    worksheet.append(HEADERS)
    for row in ROWS:
        worksheet.append([row.get(header) for header in HEADERS])
    output_path.parent.mkdir(parents=True, exist_ok=True)
    workbook.save(output_path)
    return output_path


if __name__ == "__main__":
    path = generate()
    print(f"Wrote synthetic 12Twenty export: {path}")

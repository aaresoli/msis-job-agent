import csv
import json
import logging
from datetime import datetime

import pytest
from openpyxl import Workbook

from hope_job_agent.models.job import JobPosting
from hope_job_agent.pipeline.run_mvp import run_mvp_pipeline
from hope_job_agent.sources.ksbit_export import (
    KSBIT_SOURCE_NAME,
    KsbitExportSource,
    KsbitExportSourceError,
)
from hope_job_agent.sources.registry import (
    SOURCE_REGISTRY,
    SourceStatus,
    ensure_source_allowed,
)


def _write_json(path, payload):
    path.write_text(json.dumps(payload), encoding="utf-8")


def _valid_record(**overrides):
    record = {
        "source_job_id": "ksbit-001",
        "title": "Business Analyst Intern",
        "company": "Example Analytics",
        "location": "Bloomington, IN",
        "description": "Use SQL and Python to analyze business data.",
        "apply_url": "https://example.com/ksbit/business-analyst-intern",
        "posted_date": "2026-06-01",
        "employment_type": "Internship",
        "seniority_level": "Entry",
    }
    record.update(overrides)
    return record


TWELVE_TWENTY_HEADERS = [
    "Job Posting ID",
    "External ID",
    "Job Title",
    "Company Name",
    "Company ID",
    "Status",
    "Posted Date",
    "Application Start Date",
    "Application Deadline Date",
    "Submit Date",
    "Approval Date",
    "Job Description",
    "Application URL",
    "Application Email Address",
    "Should Apply Externally",
    "Should Apply Via Email",
    "Should Apply Via Site",
    "Location",
    "Location Type",
    "Job Type",
    "Employment Type",
    "Time Commitment",
    "Work Authorization Requirement",
    "Other Work Authorization",
    "Eligible Majors / Programs",
    "Employer Industry",
    "Job Functions",
    "Company Industries",
    "Company Website",
    "Company Employee Count",
    "Company Location Address",
    "Company Overview",
    "Company LinkedIn URL",
    "Application Count",
    "Distinct Applicant Count",
    "First Application Date",
    "Last Application Date",
    "Source Has JobPostings Row",
    "Source Has JobPostingDetails Row",
]


def _valid_12twenty_record(**overrides):
    record = {
        "Job Posting ID": "35006705400001",
        "External ID": "NULL",
        "Job Title": "Data Analyst Intern",
        "Company Name": "Example Analytics",
        "Company ID": "181499997700001",
        "Status": "Application Open",
        "Posted Date": datetime(2026, 6, 23, 6, 19, 59),
        "Application Start Date": "NULL",
        "Application Deadline Date": datetime(2026, 7, 30, 4, 0, 0),
        "Submit Date": "NULL",
        "Approval Date": "NULL",
        "Job Description": (
            "<p>Build SQL &amp; Python dashboards.</p>"
            "<ul><li>Partner with business teams.</li></ul>"
        ),
        "Application URL": "https://example.com/12twenty/data-analyst-intern",
        "Application Email Address": "NULL",
        "Should Apply Externally": 1,
        "Should Apply Via Email": "NULL",
        "Should Apply Via Site": "NULL",
        "Location": (
            '{"Rank":0,"CountryId":1,"CountryName":"United States (USA)",'
            '"CityId":25554,"CityName":"Bloomington - IN"}'
        ),
        "Location Type": "Specify Location(s)",
        "Job Type": "Internship",
        "Employment Type": "NULL",
        "Time Commitment": "NULL",
        "Work Authorization Requirement": "All Work Authorizations Accepted",
        "Other Work Authorization": "NULL",
        "Eligible Majors / Programs": "MS in Information Systems",
        "Employer Industry": "Technology",
        "Job Functions": "Data Analytics",
        "Company Industries": "Software",
        "Company Website": "https://example.com",
        "Company Employee Count": "100-500",
        "Company Location Address": "Bloomington, IN",
        "Company Overview": "Example company",
        "Company LinkedIn URL": "https://www.linkedin.com/company/example",
        "Application Count": 99,
        "Distinct Applicant Count": 88,
        "First Application Date": datetime(2026, 6, 24, 1, 0, 0),
        "Last Application Date": datetime(2026, 6, 25, 1, 0, 0),
        "Source Has JobPostings Row": 1,
        "Source Has JobPostingDetails Row": 1,
    }
    record.update(overrides)
    return record


def _write_12twenty_xlsx(path, records, *, headers=None, leading_blank_row=False):
    workbook = Workbook()
    worksheet = workbook.active
    if leading_blank_row:
        worksheet.append([])
    resolved_headers = headers or TWELVE_TWENTY_HEADERS
    worksheet.append(resolved_headers)
    for record in records:
        worksheet.append([record.get(header) for header in resolved_headers])
    workbook.save(path)


def _write_profiles(path):
    path.write_text(
        json.dumps(
            {
                "profiles": [
                    {
                        "student_id": "student-001",
                        "name": "Data Student",
                        "concentration": "Data Analytics and AI",
                        "academic_stage": "Incoming student (Fall)",
                        "target_roles": ["Data Analyst / BI Engineer"],
                        "skills": ["SQL", "Python"],
                        "work_auth_status": "Need CPT / OPT sponsorship",
                        "geo_preference": ["Midwest (Chicago, Indy, Cincy)"],
                        "delivery_preference": "Dashboard / spreadsheet view",
                        "ai_matching_consent": True,
                    }
                ]
            }
        ),
        encoding="utf-8",
    )


def test_ksbit_export_loads_json_list_input(tmp_path):
    export_path = tmp_path / "ksbit_jobs.json"
    _write_json(export_path, [_valid_record()])

    result = KsbitExportSource(export_path).fetch_jobs_with_warnings()

    assert result.raw_count == 1
    assert result.loaded_count == 1
    assert result.skipped_count == 0
    assert result.returned_count == 1
    assert result.jobs[0].source == KSBIT_SOURCE_NAME
    assert result.jobs[0].source_job_id == "ksbit-001"
    assert result.jobs[0].raw_metadata["raw_payload"]["title"] == (
        "Business Analyst Intern"
    )
    assert "ingested_at" in result.jobs[0].raw_metadata
    assert result.jobs[0].retrieved_at is not None


def test_ksbit_export_loads_wrapped_json_input(tmp_path):
    export_path = tmp_path / "ksbit_jobs.json"
    _write_json(export_path, {"results": [_valid_record(source_job_id="ksbit-002")]})

    jobs = KsbitExportSource(export_path).fetch_jobs()

    assert len(jobs) == 1
    assert jobs[0].source_job_id == "ksbit-002"


def test_ksbit_export_loads_csv_input(tmp_path):
    export_path = tmp_path / "ksbit_jobs.csv"
    with export_path.open("w", newline="", encoding="utf-8") as csv_file:
        writer = csv.DictWriter(
            csv_file,
            fieldnames=[
                "job_id",
                "job_title",
                "employer_name",
                "work_location",
                "job_description",
                "job_url",
            ],
        )
        writer.writeheader()
        writer.writerow(
            {
                "job_id": "ksbit-csv-001",
                "job_title": "Analytics Intern",
                "employer_name": "Example Analytics",
                "work_location": "Chicago, IL",
                "job_description": "Build SQL reports and Python dashboards.",
                "job_url": "https://example.com/ksbit/analytics-intern",
            }
        )

    jobs = KsbitExportSource(export_path).fetch_jobs()

    assert len(jobs) == 1
    assert jobs[0].title == "Analytics Intern"
    assert jobs[0].company == "Example Analytics"
    assert jobs[0].url == "https://example.com/ksbit/analytics-intern"


def test_ksbit_export_loads_12twenty_xlsx_input(tmp_path):
    export_path = tmp_path / "12twenty_jobs.xlsx"
    _write_12twenty_xlsx(
        export_path,
        [_valid_12twenty_record()],
        leading_blank_row=True,
    )

    result = KsbitExportSource(export_path).fetch_jobs_with_warnings()

    assert result.raw_count == 1
    assert result.loaded_count == 1
    assert result.skipped_count == 0
    assert result.returned_count == 1
    job = result.jobs[0]
    assert job.source == KSBIT_SOURCE_NAME
    assert job.source_job_id == "35006705400001"
    assert job.title == "Data Analyst Intern"
    assert job.company == "Example Analytics"
    assert job.location == "Bloomington, IN"
    assert job.description == (
        "Build SQL & Python dashboards. Partner with business teams."
    )
    assert job.url == "https://example.com/12twenty/data-analyst-intern"
    assert job.posted_date.isoformat() == "2026-06-23"
    assert job.employment_type == "Internship"
    assert job.opt_cpt_flag is True
    assert job.raw_metadata["source_format"] == "xlsx"
    assert job.raw_metadata["source_row_number"] == 3
    assert job.raw_metadata["raw_payload"]["Job Description"].startswith("<p>")
    assert job.raw_metadata["raw_payload"]["External ID"] is None
    assert "Application Count" not in job.raw_metadata["raw_payload"]
    assert "Distinct Applicant Count" not in job.raw_metadata["raw_payload"]
    assert "First Application Date" not in job.raw_metadata["raw_payload"]
    assert "Last Application Date" not in job.raw_metadata["raw_payload"]


def test_ksbit_export_creates_job_posting_and_preserves_safe_xlsx_metadata(tmp_path):
    export_path = tmp_path / "12twenty_jobs.xlsx"
    _write_12twenty_xlsx(
        export_path,
        [
            _valid_12twenty_record(
                **{
                    "Job Posting ID": "metadata-job",
                    "External ID": "REQ-2026-001",
                    "Job Title": "Product Analytics Intern",
                    "Company Name": "Metadata Labs",
                    "Posted Date": datetime(2026, 7, 1, 9, 15, 0),
                    "Job Description": (
                        "<div>Analyze product funnels.</div>"
                        "<p>Build SQL dashboards.</p>"
                    ),
                    "Application URL": "https://example.com/12twenty/metadata-job",
                    "Location": (
                        '{"Rank":0,"CountryName":"United States (USA)",'
                        '"CityName":"Indianapolis - IN"}'
                    ),
                    "Job Type": "Internship",
                    "Work Authorization Requirement": (
                        "All Work Authorizations Accepted"
                    ),
                    "Employer Industry": "Analytics",
                    "Company Overview": "Safe source context",
                }
            )
        ],
        leading_blank_row=True,
    )

    result = KsbitExportSource(export_path).fetch_jobs_with_warnings()
    job = result.jobs[0]
    raw_payload = job.raw_metadata["raw_payload"]

    assert isinstance(job, JobPosting)
    assert job.source == KSBIT_SOURCE_NAME
    assert job.source_job_id == "metadata-job"
    assert job.title == "Product Analytics Intern"
    assert job.company == "Metadata Labs"
    assert job.location == "Indianapolis, IN"
    assert job.description == "Analyze product funnels. Build SQL dashboards."
    assert job.url == "https://example.com/12twenty/metadata-job"
    assert job.posted_date.isoformat() == "2026-07-01"
    assert job.employment_type == "Internship"
    assert job.seniority is None
    assert job.opt_cpt_flag is True
    assert job.retrieved_at is not None
    assert job.raw_metadata["source_format"] == "xlsx"
    assert job.raw_metadata["source_row_number"] == 3
    assert job.raw_metadata["source_job_id_was_generated"] is False
    assert "ingested_at" in job.raw_metadata
    assert raw_payload["External ID"] == "REQ-2026-001"
    assert raw_payload["Employer Industry"] == "Analytics"
    assert raw_payload["Company Overview"] == "Safe source context"
    assert raw_payload["Posted Date"] == "2026-07-01T09:15:00"
    assert raw_payload["Application Email Address"] is None
    assert "Application Count" not in raw_payload
    assert "Distinct Applicant Count" not in raw_payload
    assert "First Application Date" not in raw_payload
    assert "Last Application Date" not in raw_payload


def test_ksbit_export_filters_12twenty_xlsx_statuses_by_default(tmp_path):
    export_path = tmp_path / "12twenty_jobs.xlsx"
    _write_12twenty_xlsx(
        export_path,
        [
            _valid_12twenty_record(
                **{
                    "Job Posting ID": "open",
                    "Application URL": "https://example.com/12twenty/open",
                    "Status": "Application Open",
                }
            ),
            _valid_12twenty_record(
                **{
                    "Job Posting ID": "rejected",
                    "Application URL": "https://example.com/12twenty/rejected",
                    "Status": "Rejected",
                }
            ),
        ],
    )

    result = KsbitExportSource(export_path).fetch_jobs_with_warnings()

    assert result.raw_count == 2
    assert result.loaded_count == 1
    assert result.skipped_count == 1
    assert [job.source_job_id for job in result.jobs] == ["open"]
    assert any("Rejected=1" in warning for warning in result.warnings)


def test_ksbit_export_can_include_all_12twenty_statuses(tmp_path):
    export_path = tmp_path / "12twenty_jobs.xlsx"
    _write_12twenty_xlsx(
        export_path,
        [
            _valid_12twenty_record(
                **{
                    "Job Posting ID": "open",
                    "Application URL": "https://example.com/12twenty/open",
                    "Status": "Application Open",
                }
            ),
            _valid_12twenty_record(
                **{
                    "Job Posting ID": "closed",
                    "Application URL": "https://example.com/12twenty/closed",
                    "Status": "Application Closed",
                }
            ),
        ],
    )

    result = KsbitExportSource(
        export_path,
        allowed_statuses=None,
    ).fetch_jobs_with_warnings()

    assert result.raw_count == 2
    assert result.loaded_count == 2
    assert result.skipped_count == 0
    assert [job.source_job_id for job in result.jobs] == ["open", "closed"]


def test_ksbit_export_maps_12twenty_work_authorization(tmp_path):
    export_path = tmp_path / "12twenty_jobs.xlsx"
    _write_12twenty_xlsx(
        export_path,
        [
            _valid_12twenty_record(
                **{
                    "Job Posting ID": "all-auth",
                    "Application URL": "https://example.com/12twenty/all-auth",
                    "Work Authorization Requirement": (
                        "All Work Authorizations Accepted"
                    ),
                }
            ),
            _valid_12twenty_record(
                **{
                    "Job Posting ID": "stem",
                    "Application URL": "https://example.com/12twenty/stem",
                    "Work Authorization Requirement": "STEM Eligible Degree",
                }
            ),
            _valid_12twenty_record(
                **{
                    "Job Posting ID": "permanent",
                    "Application URL": "https://example.com/12twenty/permanent",
                    "Work Authorization Requirement": (
                        "Permanent US Work Authorization Required"
                    ),
                }
            ),
            _valid_12twenty_record(
                **{
                    "Job Posting ID": "citizen",
                    "Application URL": "https://example.com/12twenty/citizen",
                    "Work Authorization Requirement": (
                        "Other Work Authorization Required"
                    ),
                    "Other Work Authorization": "Must be a US citizen",
                }
            ),
            _valid_12twenty_record(
                **{
                    "Job Posting ID": "missing",
                    "Application URL": "https://example.com/12twenty/missing",
                    "Work Authorization Requirement": "NULL",
                    "Other Work Authorization": "NULL",
                }
            ),
        ],
    )

    jobs = KsbitExportSource(export_path).fetch_jobs()

    assert {job.source_job_id: job.opt_cpt_flag for job in jobs} == {
        "all-auth": True,
        "stem": True,
        "permanent": False,
        "citizen": False,
        "missing": None,
    }


def test_ksbit_export_uses_remote_location_type_for_12twenty_xlsx(tmp_path):
    export_path = tmp_path / "12twenty_jobs.xlsx"
    _write_12twenty_xlsx(
        export_path,
        [
            _valid_12twenty_record(
                **{
                    "Job Posting ID": "remote",
                    "Application URL": "https://example.com/12twenty/remote",
                    "Location": "NULL",
                    "Location Type": "Remote/Telecommute",
                }
            )
        ],
    )

    job = KsbitExportSource(export_path).fetch_jobs()[0]

    assert job.location == "Remote"


def test_ksbit_export_skips_12twenty_xlsx_rows_missing_required_fields(tmp_path):
    export_path = tmp_path / "12twenty_jobs.xlsx"
    _write_12twenty_xlsx(
        export_path,
        [
            _valid_12twenty_record(
                **{
                    "Job Posting ID": "valid",
                    "Application URL": "https://example.com/12twenty/valid",
                }
            ),
            _valid_12twenty_record(
                **{
                    "Job Posting ID": "email-only",
                    "Application URL": "NULL",
                    "Application Email Address": "jobs@example.com",
                }
            ),
            _valid_12twenty_record(
                **{
                    "Job Posting ID": "site-only",
                    "Application URL": "NULL",
                    "Should Apply Via Site": 1,
                }
            ),
        ],
    )

    result = KsbitExportSource(export_path).fetch_jobs_with_warnings()

    assert result.raw_count == 3
    assert result.loaded_count == 1
    assert result.skipped_count == 2
    assert [job.source_job_id for job in result.jobs] == ["valid"]
    assert any(
        "missing required field(s): apply_url" in warning for warning in result.warnings
    )
    assert any("Skipped 2 KSBIT rows" in warning for warning in result.warnings)


def test_ksbit_export_rejects_empty_xlsx_without_header_row(tmp_path):
    export_path = tmp_path / "empty.xlsx"
    workbook = Workbook()
    workbook.save(export_path)

    with pytest.raises(KsbitExportSourceError, match="header row"):
        KsbitExportSource(export_path).fetch_jobs()


def test_ksbit_export_rejects_xlsx_missing_required_headers(tmp_path):
    export_path = tmp_path / "missing_headers.xlsx"
    headers = [
        header for header in TWELVE_TWENTY_HEADERS if header != "Application URL"
    ]
    _write_12twenty_xlsx(export_path, [_valid_12twenty_record()], headers=headers)

    with pytest.raises(KsbitExportSourceError, match="missing required header"):
        KsbitExportSource(export_path).fetch_jobs()


@pytest.mark.parametrize(
    ("missing_header", "expected_missing_field"),
    [
        ("Job Title", "title"),
        ("Company Name", "company"),
        ("Job Description", "description"),
        ("Application URL", "apply_url"),
    ],
)
def test_ksbit_export_rejects_xlsx_missing_each_required_header(
    tmp_path,
    missing_header,
    expected_missing_field,
):
    export_path = tmp_path / f"missing_{expected_missing_field}.xlsx"
    headers = [header for header in TWELVE_TWENTY_HEADERS if header != missing_header]
    _write_12twenty_xlsx(export_path, [_valid_12twenty_record()], headers=headers)

    with pytest.raises(KsbitExportSourceError) as exc_info:
        KsbitExportSource(export_path).fetch_jobs()

    assert "missing required header" in str(exc_info.value)
    assert expected_missing_field in str(exc_info.value)


def test_ksbit_export_skips_xlsx_rows_with_empty_required_cells(tmp_path):
    export_path = tmp_path / "empty_required_cells.xlsx"
    _write_12twenty_xlsx(
        export_path,
        [
            _valid_12twenty_record(
                **{
                    "Job Posting ID": "valid",
                    "Application URL": "https://example.com/12twenty/valid",
                }
            ),
            _valid_12twenty_record(
                **{
                    "Job Posting ID": "missing-title",
                    "Job Title": "",
                    "Application URL": "https://example.com/12twenty/missing-title",
                }
            ),
            _valid_12twenty_record(
                **{
                    "Job Posting ID": "missing-company",
                    "Company Name": "   ",
                    "Application URL": "https://example.com/12twenty/missing-company",
                }
            ),
            _valid_12twenty_record(
                **{
                    "Job Posting ID": "missing-description",
                    "Job Description": "NULL",
                    "Application URL": (
                        "https://example.com/12twenty/missing-description"
                    ),
                }
            ),
            _valid_12twenty_record(
                **{
                    "Job Posting ID": "missing-url",
                    "Application URL": "",
                }
            ),
        ],
    )

    result = KsbitExportSource(export_path).fetch_jobs_with_warnings()

    assert result.raw_count == 5
    assert result.loaded_count == 1
    assert result.skipped_count == 4
    assert result.returned_count == 1
    assert [job.source_job_id for job in result.jobs] == ["valid"]
    assert any(
        "missing required field(s): title" in warning for warning in result.warnings
    )
    assert any(
        "missing required field(s): company" in warning for warning in result.warnings
    )
    assert any(
        "missing required field(s): description" in warning
        for warning in result.warnings
    )
    assert any(
        "missing required field(s): apply_url" in warning
        for warning in result.warnings
    )


def test_ksbit_export_accepts_xlsx_rows_with_empty_optional_cells(tmp_path):
    export_path = tmp_path / "empty_optional_cells.xlsx"
    _write_12twenty_xlsx(
        export_path,
        [
            _valid_12twenty_record(
                **{
                    "Job Posting ID": "optional-empty",
                    "Application URL": "https://example.com/12twenty/optional-empty",
                    "Posted Date": "",
                    "Location": "",
                    "Location Type": "",
                    "Job Type": "",
                    "Employment Type": "",
                    "Work Authorization Requirement": "",
                    "Other Work Authorization": "",
                    "Eligible Majors / Programs": "",
                    "Job Functions": "",
                }
            )
        ],
    )

    result = KsbitExportSource(export_path).fetch_jobs_with_warnings()
    job = result.jobs[0]

    assert result.raw_count == 1
    assert result.loaded_count == 1
    assert result.skipped_count == 0
    assert job.source_job_id == "optional-empty"
    assert job.location == "Not specified"
    assert job.posted_date is None
    assert job.employment_type is None
    assert job.seniority is None
    assert job.concentration_tags == []
    assert job.role_tags == []
    assert job.opt_cpt_flag is None
    assert job.raw_metadata["raw_payload"]["Location"] is None
    assert job.raw_metadata["raw_payload"]["Posted Date"] is None


def test_ksbit_export_keeps_xlsx_row_with_invalid_posted_date(tmp_path):
    export_path = tmp_path / "invalid_posted_date.xlsx"
    _write_12twenty_xlsx(
        export_path,
        [
            _valid_12twenty_record(
                **{
                    "Job Posting ID": "invalid-date",
                    "Posted Date": "not-a-date",
                    "Application URL": "https://example.com/12twenty/invalid-date",
                }
            )
        ],
    )

    result = KsbitExportSource(export_path).fetch_jobs_with_warnings()
    job = result.jobs[0]

    assert result.raw_count == 1
    assert result.loaded_count == 1
    assert job.source_job_id == "invalid-date"
    assert job.posted_date is None
    assert job.raw_metadata["raw_payload"]["Posted Date"] == "not-a-date"


def test_ksbit_export_preserves_duplicate_xlsx_source_job_ids(tmp_path):
    export_path = tmp_path / "duplicate_job_ids.xlsx"
    _write_12twenty_xlsx(
        export_path,
        [
            _valid_12twenty_record(
                **{
                    "Job Posting ID": "duplicate-id",
                    "Job Title": "First Duplicate Role",
                    "Application URL": "https://example.com/12twenty/duplicate-one",
                }
            ),
            _valid_12twenty_record(
                **{
                    "Job Posting ID": "duplicate-id",
                    "Job Title": "Second Duplicate Role",
                    "Application URL": "https://example.com/12twenty/duplicate-two",
                }
            ),
        ],
    )

    result = KsbitExportSource(export_path).fetch_jobs_with_warnings()

    assert result.raw_count == 2
    assert result.loaded_count == 2
    assert result.skipped_count == 0
    assert [job.source_job_id for job in result.jobs] == [
        "duplicate-id",
        "duplicate-id",
    ]
    assert [job.title for job in result.jobs] == [
        "First Duplicate Role",
        "Second Duplicate Role",
    ]
    assert [job.url for job in result.jobs] == [
        "https://example.com/12twenty/duplicate-one",
        "https://example.com/12twenty/duplicate-two",
    ]


def test_ksbit_export_maps_field_aliases_and_optional_values(tmp_path):
    export_path = tmp_path / "ksbit_jobs.json"
    _write_json(
        export_path,
        [
            {
                "req_id": "req-123",
                "role": "Cybersecurity Risk Analyst",
                "organization": "Example Security",
                "city": "Indianapolis, IN",
                "summary": "Review SIEM alerts and NIST controls.",
                "post_url": "https://example.com/ksbit/security-risk",
                "created_at": "2026-06-02T10:30:00Z",
                "work_type": "Internship",
                "level": "Entry",
                "concentration_tags": "Cybersecurity; Data Analytics and AI",
                "opt_cpt_flag": "yes",
            }
        ],
    )

    job = KsbitExportSource(export_path).fetch_jobs()[0]

    assert job.source_job_id == "req-123"
    assert job.title == "Cybersecurity Risk Analyst"
    assert job.company == "Example Security"
    assert job.location == "Indianapolis, IN"
    assert job.description == "Review SIEM alerts and NIST controls."
    assert job.posted_date.isoformat() == "2026-06-02"
    assert job.employment_type == "Internship"
    assert job.seniority == "Entry"
    assert job.concentration_tags == ["Cybersecurity", "Data Analytics and AI"]
    assert job.opt_cpt_flag is True


def test_ksbit_export_skips_invalid_rows_with_warnings(tmp_path):
    export_path = tmp_path / "ksbit_jobs.json"
    _write_json(export_path, [_valid_record(), _valid_record(apply_url="")])

    result = KsbitExportSource(export_path).fetch_jobs_with_warnings()

    assert result.raw_count == 2
    assert result.loaded_count == 1
    assert result.skipped_count == 1
    assert result.returned_count == 1
    assert result.warnings
    assert "missing required field(s): apply_url" in result.warnings[0]


def test_ksbit_export_logs_counts_without_raw_payload(tmp_path, caplog):
    export_path = tmp_path / "ksbit_jobs.json"
    _write_json(export_path, [_valid_record(), _valid_record(apply_url="")])

    with caplog.at_level(logging.INFO, logger="hope_job_agent.sources.ksbit_export"):
        KsbitExportSource(export_path).fetch_jobs_with_warnings()

    log_text = caplog.text
    assert "Loading KSBIT export from" in log_text
    assert "Loaded KSBIT export: raw=2 loaded=1 skipped=1 returned=1" in log_text
    assert "missing required field(s): apply_url" in log_text
    assert "Use SQL and Python to analyze business data." not in log_text
    assert "https://example.com/ksbit/business-analyst-intern" not in log_text


def test_ksbit_export_rejects_empty_files(tmp_path):
    export_path = tmp_path / "empty.json"
    _write_json(export_path, [])

    with pytest.raises(KsbitExportSourceError, match="empty"):
        KsbitExportSource(export_path).fetch_jobs()


def test_ksbit_export_rejects_unsupported_extensions(tmp_path):
    export_path = tmp_path / "ksbit_jobs.txt"
    export_path.write_text("not supported", encoding="utf-8")

    with pytest.raises(KsbitExportSourceError, match="Unsupported"):
        KsbitExportSource(export_path).fetch_jobs()


def test_ksbit_export_generates_stable_fallback_source_job_id(tmp_path):
    export_path = tmp_path / "ksbit_jobs.json"
    record = _valid_record(source_job_id=None)
    del record["source_job_id"]
    _write_json(export_path, [record])

    first_job = KsbitExportSource(export_path).fetch_jobs()[0]
    second_job = KsbitExportSource(export_path).fetch_jobs()[0]

    assert first_job.source_job_id == second_job.source_job_id
    assert first_job.source_job_id is not None
    assert first_job.source_job_id.startswith("ksbit-")
    assert first_job.raw_metadata["source_job_id_was_generated"] is True


def test_ksbit_export_filters_since_date_and_includes_missing_dates(tmp_path):
    export_path = tmp_path / "ksbit_jobs.json"
    _write_json(
        export_path,
        [
            _valid_record(source_job_id="old", posted_date="2026-05-01"),
            _valid_record(
                source_job_id="new",
                title="New Analytics Intern",
                apply_url="https://example.com/ksbit/new-analytics",
                posted_date="2026-06-03",
            ),
            _valid_record(
                source_job_id="missing-date",
                title="Missing Date Job",
                apply_url="https://example.com/ksbit/missing-date",
                posted_date="not-a-date",
            ),
        ],
    )

    result = KsbitExportSource(
        export_path,
        since_date="2026-06-01",
    ).fetch_jobs_with_warnings()

    assert [job.source_job_id for job in result.jobs] == ["new", "missing-date"]
    assert result.returned_count == 2
    assert any(
        "without parseable posted_date" in warning for warning in result.warnings
    )


def test_ksbit_export_applies_limit_after_filtering(tmp_path):
    export_path = tmp_path / "ksbit_jobs.json"
    _write_json(
        export_path,
        [
            _valid_record(source_job_id="one", posted_date="2026-06-01"),
            _valid_record(
                source_job_id="two",
                title="Second Analyst",
                apply_url="https://example.com/ksbit/second",
                posted_date="2026-06-02",
            ),
        ],
    )

    result = KsbitExportSource(
        export_path,
        since_date="2026-06-01",
        limit=1,
    ).fetch_jobs_with_warnings()

    assert result.returned_count == 1
    assert result.jobs[0].source_job_id == "one"


def test_ksbit_export_source_registry_loading():
    metadata = ensure_source_allowed(KSBIT_SOURCE_NAME)

    assert SOURCE_REGISTRY[KSBIT_SOURCE_NAME].status is SourceStatus.APPROVED
    assert metadata.name == KSBIT_SOURCE_NAME


def test_ksbit_export_is_compatible_with_mvp_runner(tmp_path):
    export_path = tmp_path / "ksbit_jobs.json"
    profiles_path = tmp_path / "profiles.json"
    output_path = tmp_path / "mvp_results.csv"
    database_path = tmp_path / "mvp.sqlite3"
    _write_json(export_path, [_valid_record()])
    _write_profiles(profiles_path)

    result = run_mvp_pipeline(
        source_name=KSBIT_SOURCE_NAME,
        input_path=export_path,
        profiles_path=profiles_path,
        output_path=output_path,
        database_url=f"sqlite:///{database_path.as_posix()}",
    )

    assert output_path.exists()
    assert database_path.exists()
    assert result.summary["source"] == KSBIT_SOURCE_NAME
    assert result.summary["raw_count"] == 1
    assert result.summary["unique_count"] == 1
    assert result.summary["total_ranked_matches"] == 1


def test_ksbit_export_xlsx_is_compatible_with_mvp_runner(tmp_path):
    export_path = tmp_path / "12twenty_jobs.xlsx"
    profiles_path = tmp_path / "profiles.json"
    output_path = tmp_path / "mvp_results.csv"
    database_path = tmp_path / "mvp.sqlite3"
    _write_12twenty_xlsx(export_path, [_valid_12twenty_record()])
    _write_profiles(profiles_path)

    result = run_mvp_pipeline(
        source_name=KSBIT_SOURCE_NAME,
        input_path=export_path,
        profiles_path=profiles_path,
        output_path=output_path,
        database_url=f"sqlite:///{database_path.as_posix()}",
    )

    assert output_path.exists()
    assert database_path.exists()
    assert result.summary["source"] == KSBIT_SOURCE_NAME
    assert result.summary["raw_count"] == 1
    assert result.summary["unique_count"] == 1
    assert result.summary["total_ranked_matches"] == 1

from hope_job_agent.sources.company_careers.config import CompanyTarget
from hope_job_agent.sources.company_careers.verification import verify_target

from .conftest import make_client


def _greenhouse_target() -> CompanyTarget:
    return CompanyTarget(
        company_name="Acme",
        ats_provider="greenhouse",
        ats_slug="acme",
        enabled=True,
        verification_status="verified",
    )


def test_verify_greenhouse_ok(transport):
    transport.route(
        method="GET",
        contains="boards-api.greenhouse.io/v1/boards/acme/jobs",
        body={"jobs": [{"id": 1}, {"id": 2}], "meta": {"total": 2}},
    )
    outcome = verify_target(make_client(transport), _greenhouse_target())
    assert outcome.status == "verified"
    assert outcome.jobs_total == 2
    assert outcome.http_status == 200


def test_verify_workday_blocked(transport):
    transport.route(
        method="POST",
        contains="/wday/cxs/acme/External/jobs",
        body={"error": "denied"},
        status=403,
    )
    target = CompanyTarget(
        company_name="Acme",
        ats_provider="workday",
        host="acme.wd1.myworkdayjobs.com",
        tenant="acme",
        site="External",
    )
    outcome = verify_target(make_client(transport), target)
    assert outcome.status == "blocked"
    assert outcome.http_status == 403


def test_verify_oracle_empty(transport):
    transport.route(
        method="GET",
        contains="recruitingCEJobRequisitions",
        body={"items": [{"TotalJobsCount": 0}]},
    )
    target = CompanyTarget(
        company_name="Acme",
        ats_provider="oraclecloud",
        host="acme.fa.us2.oraclecloud.com",
        site="CX_1",
    )
    outcome = verify_target(make_client(transport), target)
    assert outcome.status == "empty"
    assert outcome.jobs_total == 0


def test_verify_lever_list_payload(transport):
    transport.route(
        method="GET",
        contains="api.lever.co/v0/postings/acme",
        body=[{"id": "1"}],
    )
    target = CompanyTarget(
        company_name="Acme", ats_provider="lever", ats_slug="acme"
    )
    outcome = verify_target(make_client(transport), target)
    assert outcome.status == "verified"
    assert outcome.jobs_total == 1


def test_verify_static_provider_reports_unsupported(transport):
    target = CompanyTarget(company_name="Acme", ats_provider="static")
    outcome = verify_target(make_client(transport), target)
    assert outcome.status == "unsupported_provider"

"""Coverage for digest rendering and the shared SMTP transport.

``build_email_digest`` existed for the whole life of the project with no caller:
the digest endpoint only wrote in-app notifications, so no student ever received
mail. These tests pin the path that now reaches it.
"""

from __future__ import annotations

from email.message import EmailMessage

import pytest

from hope_job_agent.delivery.email_digest import build_email_digest
from hope_job_agent.delivery.smtp import send_message
from hope_job_agent.models.job import JobPosting
from hope_job_agent.models.match import JobMatch
from hope_job_agent.ops.digests import CADENCES, UnsupportedCadence, queue_digests
from hope_job_agent.platform.settings import PlatformSettings

pytestmark = pytest.mark.unit


class _FakeSMTP:
    """Minimal stand-in for smtplib.SMTP recording what a send would do."""

    instances: list[_FakeSMTP] = []

    def __init__(self, host: str, port: int, timeout: int) -> None:
        self.host = host
        self.port = port
        self.timeout = timeout
        self.started_tls = False
        self.logged_in: tuple[str, str] | None = None
        self.sent: list[EmailMessage] = []
        _FakeSMTP.instances.append(self)

    def __enter__(self) -> _FakeSMTP:
        return self

    def __exit__(self, *_args: object) -> None:
        return None

    def starttls(self) -> None:
        self.started_tls = True

    def login(self, username: str, password: str) -> None:
        self.logged_in = (username, password)

    def send_message(self, message: EmailMessage) -> None:
        self.sent.append(message)


@pytest.fixture(autouse=True)
def _reset_smtp(monkeypatch: pytest.MonkeyPatch) -> None:
    _FakeSMTP.instances = []
    monkeypatch.setattr("hope_job_agent.delivery.smtp.smtplib.SMTP", _FakeSMTP)


def _message() -> EmailMessage:
    message = EmailMessage()
    message["Subject"] = "Your daily HOPE career brief"
    message["To"] = "student@example.edu"
    message.set_content("body")
    return message


def test_send_is_a_no_op_without_a_configured_host() -> None:
    """An unset SMTP_HOST is a supported deployment, not a failure.

    A digest run over hundreds of students must not abort because mail is not
    configured, so this reports False rather than raising.
    """

    assert send_message(_message(), PlatformSettings(smtp_host="")) is False
    assert _FakeSMTP.instances == []


def test_send_uses_starttls_and_credentials_when_configured() -> None:
    settings = PlatformSettings(
        smtp_host="smtp.example.edu",
        smtp_port=587,
        smtp_starttls=True,
        smtp_username="hope",
        smtp_password="secret",
    )

    assert send_message(_message(), settings) is True

    client = _FakeSMTP.instances[0]
    assert (client.host, client.port) == ("smtp.example.edu", 587)
    assert client.started_tls is True
    assert client.logged_in == ("hope", "secret")


def test_plain_smtp_is_opt_in_only() -> None:
    """Mailpit speaks plain SMTP; a real relay must never be downgraded silently."""

    settings = PlatformSettings(
        smtp_host="mailpit", smtp_port=1025, smtp_starttls=False
    )

    assert send_message(_message(), settings) is True
    assert _FakeSMTP.instances[0].started_tls is False


def test_sender_comes_from_settings_not_the_caller() -> None:
    settings = PlatformSettings(
        smtp_host="mailpit", smtp_starttls=False, smtp_from="HOPE <no-reply@hope.local>"
    )

    send_message(_message(), settings)

    assert _FakeSMTP.instances[0].sent[0]["From"] == "HOPE <no-reply@hope.local>"


def _match(title: str, score: float) -> JobMatch:
    return JobMatch(
        job=JobPosting(
            source="company_careers",
            source_job_id=title,
            title=title,
            company="Example Analytics",
            location="Indianapolis, IN",
            description="A role description long enough to be realistic.",
            url=f"https://example.com/{title}",
        ),
        score=score,
        reasons=["Matches your Data Analytics and AI concentration"],
    )


def test_digest_body_lists_every_match() -> None:
    body = build_email_digest("Avery", [_match("Data Analyst", 91.2)])

    assert "Hello Avery," in body
    assert "Data Analyst at Example Analytics" in body
    assert "91.2" in body


def test_digest_body_handles_a_student_with_no_matches() -> None:
    assert "No matches are available yet." in build_email_digest("Avery", [])


def test_queue_digests_rejects_an_unknown_cadence() -> None:
    with pytest.raises(UnsupportedCadence):
        queue_digests(object(), "hourly")  # type: ignore[arg-type]


def test_supported_cadences_match_the_schedule() -> None:
    """The two beat entries and the accepted cadences must not drift apart."""

    from hope_job_agent.workers.schedules import BEAT_SCHEDULE

    scheduled = {
        entry["kwargs"]["cadence"]
        for entry in BEAT_SCHEDULE.values()
        if entry["task"] == "hope.ops.send_digests"
    }
    assert scheduled == set(CADENCES)

"""The one SMTP transport.

Both outbound mail paths -- magic links and student digests -- send through
:func:`send_message`. Keeping a single implementation matters more than the
handful of lines it saves: ``smtp_starttls`` is a security decision (see the
comment on it in :mod:`hope_job_agent.platform.settings`), and a second copy of
this function is a second place for that decision to drift.
"""

from __future__ import annotations

import logging
import smtplib
from email.message import EmailMessage

from hope_job_agent.platform.settings import PlatformSettings

LOGGER = logging.getLogger(__name__)

SMTP_TIMEOUT_SECONDS = 15


def send_message(message: EmailMessage, settings: PlatformSettings) -> bool:
    """Send ``message``; return whether it was handed to a relay.

    An unset ``SMTP_HOST`` is a supported configuration, not an error: the
    platform runs without mail and the caller decides whether that degrades
    anything. It returns ``False`` rather than raising so a digest run over
    hundreds of students does not abort on the first recipient.
    """

    if not settings.smtp_host:
        return False
    message["From"] = settings.smtp_from
    with smtplib.SMTP(
        settings.smtp_host, settings.smtp_port, timeout=SMTP_TIMEOUT_SECONDS
    ) as client:
        if settings.smtp_starttls:
            client.starttls()
        if settings.smtp_username:
            client.login(
                settings.smtp_username, settings.smtp_password.get_secret_value()
            )
        client.send_message(message)
    return True

"""Minimal SMTP email-sending utility.

Wraps the standard library's smtplib so callers (currently the Celery
notification task) don't repeat connection and message-building
boilerplate. Deliberately dependency-free: for a project this size, a
third-party mail client library would be one more moving part without
a corresponding benefit over `smtplib` + `email.message`.
"""

import logging
import smtplib
from email.message import EmailMessage

from app.core.config import get_settings

logger = logging.getLogger(__name__)


def send_email(*, to: list[str], subject: str, body: str) -> None:
    """Send a plain-text email to one or more recipients.

    Connects to the SMTP server on every call rather than pooling a
    connection, since this is invoked from short-lived Celery tasks
    fired at most a few times per alert, not on a hot path.

    Args:
        to: Recipient email addresses. If empty, the call is a no-op.
        subject: The email subject line.
        body: The plain-text email body.

    Raises:
        smtplib.SMTPException: If the SMTP server rejects the
            connection, authentication, or the message itself.
    """
    if not to:
        logger.warning("send_email called with no recipients; skipping send.")
        return

    settings = get_settings()

    message = EmailMessage()
    message["Subject"] = subject
    message["From"] = settings.smtp_from_email
    message["To"] = ", ".join(to)
    message.set_content(body)

    with smtplib.SMTP(settings.smtp_host, settings.smtp_port) as client:
        if settings.smtp_use_tls:
            client.starttls()
        if settings.smtp_user and settings.smtp_password:
            client.login(settings.smtp_user, settings.smtp_password)
        client.send_message(message)

    logger.info("Sent email '%s' to %d recipient(s).", subject, len(to))

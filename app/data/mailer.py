"""Email sending with graceful degradation.

If SMTP is configured (env), send for real via stdlib smtplib — no new dependency. If it is not
(dev / fresh clone), log the message instead of sending, so the digest job is fully exercisable
without an email account. Mirrors the OAuth "configure to activate" pattern.
"""
import logging
import smtplib
from email.message import EmailMessage

from ..core.config import settings

log = logging.getLogger(__name__)


def send_email(to: str, subject: str, html: str) -> bool:
    """Send an HTML email. Returns True if actually sent, False in dev-log mode."""
    if not settings.smtp_host:
        log.info("[email:dev] would send to=%s subject=%r\n%s", to, subject, html)
        return False
    msg = EmailMessage()
    msg["From"] = settings.email_from
    msg["To"] = to
    msg["Subject"] = subject
    msg.set_content("This is an HTML email — open it in an HTML-capable client.")
    msg.add_alternative(html, subtype="html")
    with smtplib.SMTP(settings.smtp_host, settings.smtp_port, timeout=20) as s:
        if settings.smtp_user:
            s.starttls()
            s.login(settings.smtp_user, settings.smtp_password)
        s.send_message(msg)
    return True

import logging
import smtplib
from email.message import EmailMessage

from app.core.config import settings

logger = logging.getLogger(__name__)

SMTP_HOST = "smtp.gmail.com"
SMTP_PORT = 465


def send_email(to: str, subject: str, html: str) -> None:
    """Send an email via Gmail SMTP.

    Logs and swallows send failures — a dropped reset email shouldn't blow up
    the request (the user can just retry "forgot password"), but we do want
    it in the logs to notice outages.
    """
    if not settings.gmail_address or not settings.gmail_app_password:
        logger.warning("Gmail SMTP not configured — skipping email send to %s", to)
        return

    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = settings.gmail_address
    msg["To"] = to
    msg.set_content(html, subtype="html")

    try:
        with smtplib.SMTP_SSL(SMTP_HOST, SMTP_PORT) as server:
            server.login(settings.gmail_address, settings.gmail_app_password)
            server.send_message(msg)
    except (smtplib.SMTPException, OSError):
        logger.exception("Failed to send email to %s via Gmail SMTP", to)


def send_password_reset_email(to: str, reset_link: str) -> None:
    html = (
        f"<p>Someone requested a password reset for this account.</p>"
        f'<p><a href="{reset_link}">Click here to reset your password</a>. '
        f"This link expires in {settings.password_reset_token_expire_minutes} minutes.</p>"
        f"<p>If you didn't request this, you can ignore this email.</p>"
    )
    send_email(to=to, subject="Reset your Wellness Tracker password", html=html)
import logging
import smtplib
import socket
from email.message import EmailMessage

from app.core.config import settings

logger = logging.getLogger(__name__)

SMTP_HOST = "smtp.gmail.com"
SMTP_PORT = 587


class _IPv4SMTP(smtplib.SMTP):
    """smtplib.SMTP, but forced to connect over IPv4.

    Some hosts (Render included) resolve smtp.gmail.com's IPv6 address first
    but have no outbound IPv6 route, which fails with "Network is
    unreachable" before TLS is even attempted. Forcing AF_INET here — while
    leaving self._host as the real hostname — fixes the connection without
    breaking STARTTLS's hostname verification (which uses self._host, not
    the resolved address).
    """

    def _get_socket(self, host, port, timeout):
        addr = socket.getaddrinfo(host, port, socket.AF_INET, socket.SOCK_STREAM)[0][4]
        return socket.create_connection(addr, timeout, self.source_address)


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
        with _IPv4SMTP(SMTP_HOST, SMTP_PORT, timeout=10) as server:
            server.starttls()
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
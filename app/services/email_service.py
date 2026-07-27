import logging

import requests

from app.core.config import settings

logger = logging.getLogger(__name__)

SENDGRID_API_URL = "https://api.sendgrid.com/v3/mail/send"


def send_email(to: str, subject: str, html: str) -> None:
    """Send an email via SendGrid's HTTP API.

    Render blocks outbound SMTP entirely (confirmed: both SMTP_SSL/465 and
    STARTTLS/587 fail — the second even with IPv4 forced, timing out rather
    than erroring, the signature of a firewall drop), so a plain SMTP client
    can never work there. SendGrid's API is a normal HTTPS POST, which isn't
    blocked. `settings.mail_from` must be verified as a Single Sender in the
    SendGrid dashboard first.

    Logs and swallows send failures — a dropped reset email shouldn't blow up
    the request (the user can just retry "forgot password"), but we do want
    it in the logs to notice outages.
    """
    if not settings.sendgrid_api_key or not settings.mail_from:
        logger.warning("SendGrid not configured — skipping email send to %s", to)
        return

    try:
        response = requests.post(
            SENDGRID_API_URL,
            headers={
                "Authorization": f"Bearer {settings.sendgrid_api_key}",
                "Content-Type": "application/json",
            },
            json={
                "personalizations": [{"to": [{"email": to}]}],
                "from": {"email": settings.mail_from},
                "subject": subject,
                "content": [{"type": "text/html", "value": html}],
            },
            timeout=10,
        )
        response.raise_for_status()
    except requests.RequestException:
        logger.exception("Failed to send email to %s via SendGrid", to)


def send_password_reset_email(to: str, reset_link: str) -> None:
    html = (
        f"<p>Someone requested a password reset for this account.</p>"
        f'<p><a href="{reset_link}">Click here to reset your password</a>. '
        f"This link expires in {settings.password_reset_token_expire_minutes} minutes.</p>"
        f"<p>If you didn't request this, you can ignore this email.</p>"
    )
    send_email(to=to, subject="Reset your Wellness Tracker password", html=html)
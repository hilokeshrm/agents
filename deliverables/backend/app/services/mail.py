"""One outbound-mail door for things that are not pipeline notifications (the
sign-in one-time code). Two deliveries:

- console  -- writes the message to the application log. Development default:
              nothing to configure, and the code is visible in logs/backend.log.
- smtp     -- plain SMTP with STARTTLS and a login, which is what Gmail wants:
              SMTP_HOST=smtp.gmail.com SMTP_PORT=587 SMTP_STARTTLS=true
              SMTP_USERNAME=<gmail address> SMTP_PASSWORD=<16-char app password>
              SMTP_SENDER=<gmail address>
              (an App Password from Google Account > Security > 2-Step
              Verification; a normal account password is refused by Gmail).
"""

import logging
import smtplib
from email.message import EmailMessage

from app.core.config import settings

log = logging.getLogger("opptrack.mail")


class MailError(RuntimeError):
    pass


def send_email(to: str, subject: str, body: str) -> str:
    """Returns the delivery used ("console" or "smtp"). Raises MailError when
    SMTP is configured and refuses -- the caller decides whether that is fatal."""
    delivery = (settings.otp_delivery or "console").lower()
    if delivery == "console":
        log.warning("MAIL (console delivery) to=%s subject=%r\n%s", to, subject, body)
        return "console"
    if delivery != "smtp":
        raise MailError(f"unknown OTP_DELIVERY {delivery!r}; expected console or smtp")

    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = settings.smtp_sender
    msg["To"] = to
    msg.set_content(body)
    try:
        with smtplib.SMTP(settings.smtp_host, settings.smtp_port, timeout=15) as smtp:
            if settings.smtp_starttls:
                smtp.starttls()
            if settings.smtp_username:
                smtp.login(settings.smtp_username, settings.smtp_password or "")
            smtp.send_message(msg)
    except (smtplib.SMTPException, OSError) as exc:
        log.error("SMTP delivery to %s failed: %s", to, exc)
        raise MailError(f"mail could not be sent: {exc}") from exc
    return "smtp"

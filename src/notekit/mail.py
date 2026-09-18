"""Sending the one email this app sends.

There is no mail provider configured, and rather than pretend otherwise this
falls back to writing the message to the server log with a notice saying so.
The reset flow around it is complete and real: setting the SMTP_* variables is
the only thing between this and delivered mail.

Printing a reset link to a log is fine on a laptop and wrong on a shared host,
where anyone reading logs could take an account. `MAIL_FALLBACK_LOG` has to be
set on purpose for that to happen once SMTP is absent in production.
"""

from __future__ import annotations

import os
import smtplib
from email.message import EmailMessage


def _setting(name: str, default: str = "") -> str:
    return os.environ.get(name, default).strip()


def configured() -> bool:
    return bool(_setting("SMTP_HOST"))


def send(to: str, subject: str, body: str) -> bool:
    """Deliver, or log and say it did not. Never raises at the caller."""
    if not configured():
        if _setting("MAIL_FALLBACK_LOG").lower() in {"1", "true", "yes"}:
            print(
                "\n[mail] SMTP is not configured, so this was not sent.\n"
                f"[mail] to: {to}\n[mail] subject: {subject}\n{body}\n"
            )
        else:
            print(
                f"[mail] Would send {subject!r} to {to}, but SMTP_HOST is unset. "
                "Set SMTP_HOST/PORT/USER/PASSWORD, or MAIL_FALLBACK_LOG=1 to "
                "print the message during local development."
            )
        return False

    message = EmailMessage()
    message["From"] = _setting("MAIL_FROM", _setting("SMTP_USER"))
    message["To"] = to
    message["Subject"] = subject
    message.set_content(body)

    host = _setting("SMTP_HOST")
    port = int(_setting("SMTP_PORT", "587"))
    try:
        with smtplib.SMTP(host, port, timeout=15) as smtp:
            smtp.starttls()
            user, password = _setting("SMTP_USER"), _setting("SMTP_PASSWORD")
            if user:
                smtp.login(user, password)
            smtp.send_message(message)
        return True
    except Exception as exc:  # noqa: BLE001
        # A failure here must not tell the caller whether the address exists,
        # and must not take down the request.
        print(f"[mail] delivery failed: {exc}")
        return False

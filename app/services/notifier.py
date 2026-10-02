"""Email delivery, isolated behind an interface so the channel can change
later without touching reminder_service (PRD extension-point rule).

PRD safety rule: external calls fail safe. A 10s timeout, one retry with a
short backoff, and every exception the attempt could raise (a network
failure, or the email package itself rejecting a malformed header) is
swallowed — send() returns False rather than raising, so neither a down
SMTP server nor a task title the email package objects to ever crashes the
cron endpoint. A failed send is simply retried on the next cron run (it is
never recorded in reminders_sent on failure)."""

import logging
import smtplib
import time
from email.mime.text import MIMEText

logger = logging.getLogger(__name__)

TIMEOUT_SECONDS = 10
RETRY_BACKOFF_SECONDS = 2


class Notifier:
    def send(self, *, to: str, subject: str, body: str) -> bool:
        raise NotImplementedError


class SmtpNotifier(Notifier):
    def __init__(self, *, host: str, port: int, user: str, password: str) -> None:
        self.host = host
        self.port = port
        self.user = user
        self.password = password

    def send(self, *, to: str, subject: str, body: str) -> bool:
        for attempt in (1, 2):
            try:
                self._send_once(to, subject, body)
                return True
            except Exception as exc:  # noqa: BLE001 — must never raise, see module docstring
                logger.error("smtp_send_failed attempt=%s to=%s error=%s", attempt, to, exc)
                if attempt == 1:
                    time.sleep(RETRY_BACKOFF_SECONDS)
        return False

    def _send_once(self, to: str, subject: str, body: str) -> None:
        message = MIMEText(body)
        message["Subject"] = subject
        message["From"] = self.user
        message["To"] = to
        with smtplib.SMTP(self.host, self.port, timeout=TIMEOUT_SECONDS) as server:
            server.starttls()
            server.login(self.user, self.password)
            server.sendmail(self.user, [to], message.as_string())


def get_notifier(config) -> Notifier:
    return SmtpNotifier(
        host=config["SMTP_HOST"],
        port=config["SMTP_PORT"],
        user=config["SMTP_USER"],
        password=config["SMTP_PASSWORD"],
    )

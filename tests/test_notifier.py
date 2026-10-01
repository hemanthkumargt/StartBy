"""Exercises SmtpNotifier's actual retry/failure logic (every other test
monkeypatches .send() away entirely, so this is the only place that path
gets real coverage) by faking smtplib.SMTP itself, never touching a network."""

import smtplib

import app.services.notifier as notifier_module
from app.services.notifier import SmtpNotifier, get_notifier


class _AlwaysFailsSmtp:
    def __init__(self, *args, **kwargs):
        raise smtplib.SMTPConnectError(421, "simulated connection failure")


class _WorksSmtp:
    sent = []

    def __init__(self, *args, **kwargs):
        pass

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def starttls(self):
        pass

    def login(self, user, password):
        pass

    def sendmail(self, from_addr, to_addrs, message):
        _WorksSmtp.sent.append((from_addr, to_addrs, message))


def test_send_retries_once_then_gives_up_without_raising(monkeypatch):
    monkeypatch.setattr(notifier_module, "RETRY_BACKOFF_SECONDS", 0)
    monkeypatch.setattr(notifier_module.time, "sleep", lambda _seconds: None)
    monkeypatch.setattr(smtplib, "SMTP", _AlwaysFailsSmtp)

    notifier = SmtpNotifier(host="smtp.example.com", port=587, user="a@b.com", password="x")
    result = notifier.send(to="user@example.com", subject="Hi", body="body")

    assert result is False


def test_send_succeeds_and_delivers_the_message(monkeypatch):
    monkeypatch.setattr(smtplib, "SMTP", _WorksSmtp)
    _WorksSmtp.sent.clear()

    notifier = SmtpNotifier(host="smtp.example.com", port=587, user="a@b.com", password="x")
    result = notifier.send(to="user@example.com", subject="Due soon", body="Hello")

    assert result is True
    assert len(_WorksSmtp.sent) == 1
    from_addr, to_addrs, message = _WorksSmtp.sent[0]
    assert from_addr == "a@b.com"
    assert to_addrs == ["user@example.com"]
    assert "Due soon" in message


def test_get_notifier_reads_config():
    config = {
        "SMTP_HOST": "smtp.gmail.com",
        "SMTP_PORT": 587,
        "SMTP_USER": "demo@startby.local",
        "SMTP_PASSWORD": "app-password",
    }
    notifier = get_notifier(config)
    assert isinstance(notifier, SmtpNotifier)
    assert notifier.host == "smtp.gmail.com"
    assert notifier.user == "demo@startby.local"

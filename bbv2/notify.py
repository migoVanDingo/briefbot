"""Notification backends for per-user email.

A `Notifier` sends one message. `LogNotifier` prints it (safe default / dry-run);
`MailgunNotifier` posts to Mailgun and is only built when MAILGUN_* env is set.
"""

from __future__ import annotations

from typing import Protocol

import requests

from .config import mailgun_config


class Notifier(Protocol):
    def send(self, to: str, subject: str, body: str) -> None: ...


class LogNotifier:
    """Prints what would be sent — used for --dry-run and as a safe default."""

    def send(self, to: str, subject: str, body: str) -> None:
        print(f"\n[email] to={to}\n[email] subject={subject}\n{body}\n")


class MailgunNotifier:
    def __init__(self, api_key: str, domain: str, sender: str) -> None:
        self.api_key = api_key
        self.domain = domain
        self.sender = sender

    def send(self, to: str, subject: str, body: str) -> None:
        resp = requests.post(
            f"https://api.mailgun.net/v3/{self.domain}/messages",
            auth=("api", self.api_key),
            data={"from": self.sender, "to": to, "subject": subject, "text": body},
            timeout=20,
        )
        resp.raise_for_status()


def default_notifier(dry_run: bool = False) -> Notifier:
    """Mailgun if configured (and not a dry run), else LogNotifier."""
    if dry_run:
        return LogNotifier()
    cfg = mailgun_config()
    if cfg:
        return MailgunNotifier(cfg["api_key"], cfg["domain"], cfg["from"])
    return LogNotifier()

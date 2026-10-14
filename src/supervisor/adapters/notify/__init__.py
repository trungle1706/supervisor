"""Notifier adapters (WP8).

* ``inbox`` (always on): notices are rows in the ``notice`` state table; the console
  Inbox page lists them and a user marks them read.
* ``webhook`` (stub, off by default: ``NOTIFY_WEBHOOK_ENABLED=0``): queues the notice as
  a ``notice`` row with channel ``webhook:<channel>`` and status ``queued``. It never
  opens a network connection (offline runtime); the bank's ITSM / pager transport is a
  WP11 integration stub.
"""

from __future__ import annotations

import logging
import uuid
from collections.abc import Sequence
from typing import Any

from supervisor.core.errors import SupervisorError
from supervisor.core.ports import Clock, Masker, Notifier, StateStore

log = logging.getLogger("supervisor.notify")

MAX_SUBJECT = 200
MAX_BODY = 4000


class NoticeError(SupervisorError):
    """A notice cannot be stored or changed (HTTP 400)."""


class InboxNotifier:
    """Stores notices in the ``notice`` table. Text is masked before it is stored."""

    kind = "inbox"

    def __init__(self, state: StateStore, clock: Clock, masker: Masker | None = None) -> None:
        self.state = state
        self.clock = clock
        self.masker = masker

    def _mask(self, text: str) -> str:
        return self.masker.mask(text) if self.masker is not None else text

    def _store(self, channel: str, subject: str, body: str, status: str) -> dict[str, Any]:
        return self.state.insert(
            "notice",
            {
                "notice_id": uuid.uuid4().hex,
                "ts": self.clock.now(),
                "channel": channel[:64],
                "subject": self._mask(subject)[:MAX_SUBJECT],
                "body": self._mask(body)[:MAX_BODY],
                "status": status,
                "read_by": None,
            },
        )

    def notify(self, channel: str, subject: str, body: str) -> None:
        self._store(channel, subject, body, "unread")

    def list(
        self, channel: str | None = None, status: str | None = None, limit: int = 200
    ) -> list[dict[str, Any]]:
        where: dict[str, Any] = {}
        if channel:
            where["channel"] = channel
        if status:
            where["status"] = status
        rows = self.state.query("notice", where or None)
        rows.sort(key=lambda r: r["ts"], reverse=True)
        return rows[:limit]

    def mark_read(self, notice_id: str, user_id: str, expected_version: int) -> dict[str, Any]:
        row = self.state.get("notice", {"notice_id": notice_id})
        if row is None:
            raise NoticeError(f"notice {notice_id[:64]} does not exist")
        if row["status"] != "unread":
            raise NoticeError(f"notice is {row['status']}; only unread notices can be marked read")
        return self.state.update(
            "notice",
            {"notice_id": notice_id},
            {"status": "read", "read_by": user_id},
            expected_version,
        )


class WebhookNotifierStub:
    """Off by default. Queues the notice; never sends (no network in the runtime)."""

    kind = "webhook"

    def __init__(self, inbox: InboxNotifier, url: str) -> None:
        self.inbox = inbox
        self.url_configured = bool(url.strip())

    def notify(self, channel: str, subject: str, body: str) -> None:
        self.inbox._store(f"webhook:{channel}"[:64], subject, body, "queued")
        log.info("webhook stub: notice queued for channel %s (not sent)", channel)


class FanoutNotifier:
    def __init__(self, targets: Sequence[Notifier]) -> None:
        self.targets = list(targets)

    def notify(self, channel: str, subject: str, body: str) -> None:
        for t in self.targets:
            try:
                t.notify(channel, subject, body)
            except Exception as exc:  # noqa: BLE001 - a notice must never break a case action
                log.warning("notifier %s failed: %s", type(t).__name__, type(exc).__name__)


def build_notifier(
    settings: Any, state: StateStore, clock: Clock, masker: Masker | None = None
) -> tuple[FanoutNotifier, InboxNotifier]:
    """(notifier for the case service, inbox for the console)."""
    inbox = InboxNotifier(state, clock, masker)
    targets: list[Notifier] = [inbox]
    if getattr(settings, "notify_webhook_enabled", False):
        targets.append(WebhookNotifierStub(inbox, getattr(settings, "notify_webhook_url", "")))
    return FanoutNotifier(targets), inbox


__all__ = [
    "FanoutNotifier",
    "InboxNotifier",
    "NoticeError",
    "WebhookNotifierStub",
    "build_notifier",
]

"""Notifier adapters (WP8).

* ``inbox`` (always on): notices are rows in the ``notice`` state table; the console
  Inbox page lists them and a user marks them read.
* ``webhook`` (off by default: ``NOTIFY_WEBHOOK_ENABLED=0``). With the flag on and
  ``NOTIFY_WEBHOOK_URL`` filled (WP21) ``WebhookNotifier`` POSTs each notice (masked text,
  ids) with bounded retry, an idempotency key and a dead-letter file; the ``notice`` row
  (channel ``webhook:<channel>``) is queued by ``notify`` (a console request never waits
  for the network); the scheduler job ``notify`` (``WebhookNotifier.drain``) sends it:
  ``queued`` -> ``sent`` or ``dead_letter``. With the
  flag on and the URL empty or ``FILL-ME`` the old stub queues the row and never sends.
* ``pager`` and ``itsm`` (stubs, WP21): same ``Notifier`` interface and ``kind``; they
  queue a ``notice`` row (``pager:<channel>``, ``itsm:<channel>``, status ``queued``) and
  never send. The real pager / ITSM bridges are ``adapters/integrations/pager.py`` and
  ``itsm.py`` (case-driven, fakes until the bank wires them).
"""

from __future__ import annotations

import logging
import uuid
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import Any

from supervisor.adapters.integrations import (
    IntegrationError,
    RetryPolicy,
    is_placeholder,
    with_retry,
)
from supervisor.adapters.integrations.deadletter import DeadLetter
from supervisor.adapters.integrations.transport import HttpTransport, Transport
from supervisor.core.canonical import format_ts
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


class WebhookNotifier:
    """Sends notices to a webhook (WP21). Off unless ``NOTIFY_WEBHOOK_ENABLED`` and the URL
    is filled. Body: ``{"kind", "channel", "subject", "body", "notice_id", "ts",
    "idempotency_key"}`` with the same masked text the inbox stores. Retry: ``RetryPolicy``
    (3 attempts, 1 s, 2 s). After the last failure the payload is appended to the dead-letter
    file and the notice row says ``dead_letter``; ``notify`` never raises."""

    kind = "webhook"

    def __init__(
        self,
        inbox: InboxNotifier,
        url: str,
        *,
        transport: Transport | None = None,
        retry: RetryPolicy | None = None,
        dead_letter: DeadLetter | None = None,
        timeout_s: float = 10.0,
        sleep: Callable[[float], None] | None = None,
    ) -> None:
        if is_placeholder(url):
            raise IntegrationError("NOTIFY_WEBHOOK_URL is empty or FILL-ME; the webhook is off")
        self.inbox = inbox
        self.url = url
        self.transport = transport or HttpTransport()
        self.retry = retry or RetryPolicy()
        self.dead_letter = dead_letter
        self.timeout_s = timeout_s
        self._sleep = sleep
        self.sent = 0
        self.dead_lettered = 0

    def _retrying(self, body: dict[str, Any], what: str) -> None:
        kw: dict[str, Any] = {"what": what}
        if self._sleep is not None:
            kw["sleep"] = self._sleep
        with_retry(lambda: self.transport(self.url, body, self.timeout_s), self.retry, **kw)

    def send_json(self, kind: str, key: str, doc: dict[str, Any]) -> str:
        """POST ``doc`` with idempotency key ``key``. Returns ``sent`` or ``dead_letter``."""
        body = {**doc, "kind": kind, "idempotency_key": key}
        try:
            self._retrying(body, "webhook")
        except IntegrationError as exc:
            if self.dead_letter is not None:
                self.dead_letter.put("webhook", key, body, str(exc), self.retry.attempts)
            self.dead_lettered += 1
            log.warning("webhook send failed (%s): parked in the dead-letter file", kind)
            return "dead_letter"
        self.sent += 1
        return "sent"

    def replay_dead_letter(self) -> tuple[int, int]:
        """Send the parked payloads again. Returns (sent, still_failing)."""
        if self.dead_letter is None:
            return 0, 0
        return self.dead_letter.replay(lambda e: self._retrying(e["payload"], "webhook replay"))

    def notify(self, channel: str, subject: str, body: str) -> None:
        """Queue only. Never sends: this runs on console request paths (case actions), and a
        dead webhook must not slow them (3 attempts x 10 s). The ``notify`` scheduler job calls
        ``drain``."""
        self.inbox._store(f"webhook:{channel}"[:64], subject, body, "queued")

    def drain(self, limit: int = 50) -> dict[str, int]:
        """Send queued ``webhook:*`` notices, oldest first, with retry and dead letter. Each row
        goes ``queued`` -> ``sent`` or ``dead_letter``. Never raises."""
        rows = [
            r
            for r in self.inbox.state.query("notice", {"status": "queued"})
            if str(r["channel"]).startswith("webhook:")
        ]
        rows.sort(key=lambda r: (r["ts"], r["notice_id"]))
        out = {"sent": 0, "dead_letter": 0}
        for row in rows[:limit]:
            doc = {
                "channel": str(row["channel"])[len("webhook:") :],
                "subject": row["subject"],
                "body": row["body"],
                "notice_id": row["notice_id"],
                "ts": format_ts(row["ts"]),
            }
            status = self.send_json("notice", str(row["notice_id"]), doc)
            out[status] += 1
            try:
                self.inbox.state.update(
                    "notice",
                    {"notice_id": row["notice_id"]},
                    {"status": status},
                    int(row["row_version"]),
                )
            except Exception:  # noqa: BLE001 - the send is done; the row status is a courtesy
                log.warning("webhook notice status not updated")
        return out


class StubNotifier:
    """Pager / ITSM stub with the common ``Notifier`` interface: queues a ``notice`` row
    (``<kind>:<channel>``, status ``queued``) and never sends (WP21; the real bridges are in
    ``adapters/integrations``)."""

    def __init__(self, kind: str, inbox: InboxNotifier) -> None:
        if kind not in ("pager", "itsm"):
            raise ValueError("StubNotifier kind must be pager or itsm")
        self.kind = kind
        self.inbox = inbox

    def notify(self, channel: str, subject: str, body: str) -> None:
        self.inbox._store(f"{self.kind}:{channel}"[:64], subject, body, "queued")
        log.info("%s stub: notice queued for channel %s (not sent)", self.kind, channel)


def webhook_dead_letter_path(settings: Any) -> Path:
    p = getattr(settings, "notify_webhook_dead_letter", None)
    return Path(p) if p else Path(settings.data_dir) / "notify" / "webhook.dead.jsonl"


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
        url = getattr(settings, "notify_webhook_url", "")
        if is_placeholder(url):
            targets.append(WebhookNotifierStub(inbox, url))  # no URL: queue only
        else:
            dead = DeadLetter(webhook_dead_letter_path(settings))
            secret = getattr(settings, "notify_webhook_token", None)
            transport = HttpTransport(secret.get_secret_value() if secret else None)
            targets.append(WebhookNotifier(inbox, url, transport=transport, dead_letter=dead))
    return FanoutNotifier(targets), inbox


__all__ = [
    "FanoutNotifier",
    "InboxNotifier",
    "NoticeError",
    "StubNotifier",
    "WebhookNotifier",
    "WebhookNotifierStub",
    "webhook_dead_letter_path",
    "build_notifier",
]

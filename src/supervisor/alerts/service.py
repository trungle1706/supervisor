"""Alert service: store fired alerts, send them through their routes, acknowledge (WP21).

Order for one alert: (1) insert the ``alert`` row (``alert_id`` is the key, so a replay is a
no-op), (2) record an ``alert`` entry on the evidence chain (ids, counts, hashes), (3) send to
each route and write the result into ``route_status``. A route that fails never blocks the
others and never raises; a row with a route still ``pending`` or ``failed`` is retried by
``redeliver``. Free text never enters an alert: the title is the fixed rule title.

Route status values: ``sent`` | ``queued`` (stub: stored, not sent) | ``off`` (the channel is
not enabled) | ``dead_letter`` (parked after the retries) | ``failed`` | ``pending``.
"""

from __future__ import annotations

import logging
import re
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Protocol

from supervisor.alerts.engine import FiredAlert
from supervisor.core.canonical import format_ts
from supervisor.core.errors import ConcurrencyError, DuplicateKeyError, SupervisorError
from supervisor.core.ports import Clock, EvidenceSink, StateStore

log = logging.getLogger("supervisor.alerts")

OPEN_STATUSES = ("open", "acknowledged")
RETRY_STATUSES = ("pending", "failed")
RETRY_LIMIT = 200  # rows per redeliver pass


class AlertError(SupervisorError):
    """An alert cannot be changed (HTTP 400 at the console)."""


# The stable field set of an alert row as the analyst sees it (golden test in the harness).
ALERT_FIELDS = (
    "alert_id", "ts", "dedupe_key", "rule_id", "rule_hash", "severity", "status", "title",
    "agent_id", "group_value", "window_s", "window_count", "threshold", "first_ts", "last_ts",
    "suppressed_count", "case_id", "chain_lane", "chain_seq", "entry_hash", "refs", "routes",
    "route_status", "acknowledged_by", "acknowledged_at", "correlation_id",
)  # fmt: skip


class Route(Protocol):
    """One delivery channel. ``send`` returns a route status; it may raise (caught)."""

    def send(self, alert: Mapping[str, Any]) -> str: ...


@dataclass
class Routes:
    """Name -> channel. A name with no channel reports ``off``."""

    channels: dict[str, Route] = field(default_factory=dict)

    def send(self, name: str, alert: Mapping[str, Any]) -> str:
        ch = self.channels.get(name)
        if ch is None:
            return "off"
        try:
            return ch.send(alert)
        except Exception as exc:  # noqa: BLE001 - a route must not stop the others
            log.warning("alert route %s failed: %s", name, type(exc).__name__)
            return "failed"


def triage_text(alert: Mapping[str, Any], console_base: str = "/console") -> tuple[str, str]:
    """(subject, body) for inbox / webhook / pager: everything the analyst needs to triage
    in under two minutes, as stable ``key: value`` lines. Ids and counts only."""
    who = alert.get("agent_id") or alert.get("group_value") or "-"
    subject = f"[{alert['severity']}] {alert['rule_id']} {who}"
    lines = [
        f"alert_id: {alert['alert_id']}",
        f"rule_id: {alert['rule_id']}",
        f"severity: {alert['severity']}",
        f"title: {alert['title']}",
        f"agent_id: {alert.get('agent_id') or '-'}",
        f"group: {alert.get('group_value') or '-'}",
        f"window: {alert['window_count']} of {alert['threshold']} in {alert['window_s']} s",
        f"first_ts: {_ts(alert['first_ts'])}",
        f"last_ts: {_ts(alert['last_ts'])}",
        f"suppressed_repeats: {alert.get('suppressed_count', 0)}",
        f"case: {alert.get('case_id') or '-'}",
        f"chain: {alert.get('chain_lane') or '-'}:{_n(alert.get('chain_seq'))}",
        f"entry_hash: {alert.get('entry_hash') or '-'}",
        f"console: {console_base}/metrics#alerts",
    ]
    if alert.get("correlation_id"):  # WP39: the one id that ties alert, decision and trace span
        lines.insert(-1, f"correlation_id: {alert['correlation_id']}")
    return subject, "\n".join(lines)


_CORR = re.compile(r"^[A-Za-z0-9_.:@-]{1,128}$")


def _corr(value: Any) -> str | None:
    """The correlation id of the trigger signal, only when it is a plain id (it may come from a
    caller; anything else is dropped, never stored)."""
    return str(value) if isinstance(value, str) and _CORR.match(value) else None


def _ts(v: Any) -> str:
    return format_ts(v) if isinstance(v, datetime) else str(v)


def _n(v: Any) -> str:
    return "-" if v is None else str(v)


class AlertService:
    def __init__(
        self,
        state: StateStore,
        clock: Clock,
        evidence: EvidenceSink | None = None,
        routes: Routes | None = None,
        env: str = "",
    ) -> None:
        self.state = state
        self.clock = clock
        self.evidence = evidence
        self.routes = routes or Routes()
        self.env = env

    # -- reads -----------------------------------------------------------------------
    def list(self, status: str | None = None, limit: int = 200) -> list[dict[str, Any]]:
        rows = self.state.query("alert", {"status": status} if status else None)
        rows.sort(key=lambda r: r["ts"], reverse=True)
        return rows[:limit]

    def counts(self) -> dict[str, int]:
        out = {"open": 0, "acknowledged": 0, "closed": 0}
        for r in self.state.query("alert"):
            out[r["status"]] = out.get(r["status"], 0) + 1
        return out

    def last_fired(self) -> dict[str, datetime]:
        """dedupe key -> time of its newest alert (any status): the dedupe memory."""
        out: dict[str, datetime] = {}
        for r in self.state.query("alert"):
            if r["dedupe_key"] not in out or r["ts"] > out[r["dedupe_key"]]:
                out[r["dedupe_key"]] = r["ts"]
        return out

    # -- write path ------------------------------------------------------------------
    def _case_for(self, fired: FiredAlert) -> str | None:
        if fired.trigger.case_id:
            return str(fired.trigger.case_id)
        if not fired.agent_id:
            return None
        rows = [
            r
            for r in self.state.query("cases", {"agent_id": fired.agent_id})
            if r["status"] in ("open", "triage", "escalated") and r["opened_at"] >= fired.first_ts
        ]
        if not rows:
            return None
        return str(min(rows, key=lambda r: (r["opened_at"], r["case_id"]))["case_id"])

    def row_for(self, fired: FiredAlert) -> dict[str, Any]:
        t = fired.trigger
        rule = fired.rule
        return {
            "alert_id": fired.alert_id,
            "ts": fired.ts,
            "dedupe_key": fired.dedupe_key,
            "rule_id": rule.id,
            "rule_hash": rule.rule_hash,
            "severity": rule.severity,
            "status": "open",
            "title": rule.title,
            "agent_id": fired.agent_id,
            "group_value": fired.group_value,
            "window_s": rule.window_s,
            "window_count": fired.window_count,
            "threshold": rule.threshold,
            "first_ts": fired.first_ts,
            "last_ts": fired.last_ts,
            "suppressed_count": fired.suppressed_count,
            "case_id": self._case_for(fired),
            "chain_lane": t.lane,
            "chain_seq": t.seq,
            "entry_hash": t.entry_hash,
            "refs": list(fired.refs),
            "routes": list(rule.routes),
            "route_status": {r: "pending" for r in rule.routes},
            "correlation_id": _corr(t.fields.get("correlation_id")),
        }

    def raise_alert(self, fired: FiredAlert) -> dict[str, Any] | None:
        """Store, record on the chain, send. None when the alert already exists."""
        try:
            row = self.state.insert("alert", self.row_for(fired))
        except DuplicateKeyError:
            return None
        if self.evidence is not None:
            try:
                self.evidence.record(
                    "alert",
                    f"alert:{row['alert_id']}",
                    {
                        "alert_id": row["alert_id"],
                        "rule_id": row["rule_id"],
                        "rule_hash": row["rule_hash"],
                        "severity": row["severity"],
                        "agent_id": row["agent_id"],
                        "dedupe_key": row["dedupe_key"],
                        "window_s": row["window_s"],
                        "window_count": row["window_count"],
                        "threshold": row["threshold"],
                        "case_id": row["case_id"],
                        "trigger_lane": row["chain_lane"],
                        "trigger_seq": row["chain_seq"],
                        "trigger_hash": row["entry_hash"],
                        "correlation_id": row.get("correlation_id"),
                        "ts": format_ts(row["ts"]),
                    },
                )
            except Exception:  # noqa: BLE001 - the alert row is stored; log and go on
                log.exception("alert evidence record failed")
        return self.deliver(row)

    def deliver(self, row: Mapping[str, Any]) -> dict[str, Any]:
        """Send to every route that is not yet ``sent``/``queued``/``off``; save the result."""
        status = dict(row["route_status"] or {})
        for name in row["routes"]:
            if status.get(name) in (None, *RETRY_STATUSES):
                status[name] = self.routes.send(name, row)
        return self._save_status(row["alert_id"], status)

    def _save_status(self, alert_id: str, status: dict[str, str]) -> dict[str, Any]:
        for _ in range(3):
            cur = self.state.get("alert", {"alert_id": alert_id})
            assert cur is not None
            try:
                return self.state.update(
                    "alert", {"alert_id": alert_id}, {"route_status": status}, cur["row_version"]
                )
            except ConcurrencyError:
                continue
        raise AlertError("alert route status could not be saved")

    def redeliver(self) -> int:
        """Retry routes that were ``pending`` or ``failed`` (a crash, a down webhook)."""
        n = 0
        rows = [r for r in self.state.query("alert", {"status": "open"})]
        for r in sorted(rows, key=lambda x: x["ts"])[:RETRY_LIMIT]:
            if any(v in RETRY_STATUSES for v in (r["route_status"] or {}).values()):
                self.deliver(r)
                n += 1
        return n

    def add_suppressed(self, key: str, count: int, last_ts: datetime) -> None:
        """Repeats of an earlier alert that the dedupe window absorbed."""
        rows = [r for r in self.state.query("alert", {"dedupe_key": key})]
        if not rows:
            return
        newest = max(rows, key=lambda r: r["ts"])
        for _ in range(3):
            cur = self.state.get("alert", {"alert_id": newest["alert_id"]})
            assert cur is not None
            try:
                self.state.update(
                    "alert",
                    {"alert_id": cur["alert_id"]},
                    {
                        "suppressed_count": int(cur["suppressed_count"]) + count,
                        "last_ts": max(cur["last_ts"], last_ts),
                    },
                    cur["row_version"],
                )
                return
            except ConcurrencyError:
                continue

    # -- acknowledge -------------------------------------------------------------------
    def acknowledge(self, alert_id: str, user_id: str, expected_version: int) -> dict[str, Any]:
        row = self.state.get("alert", {"alert_id": alert_id})
        if row is None:
            raise AlertError(f"alert {alert_id[:64]} does not exist")
        if row["status"] != "open":
            raise AlertError(f"alert is {row['status']}; only open alerts can be acknowledged")
        now = self.clock.now()
        new = self.state.update(
            "alert",
            {"alert_id": alert_id},
            {"status": "acknowledged", "acknowledged_by": user_id, "acknowledged_at": now},
            expected_version,
        )
        if self.evidence is not None:
            try:
                self.evidence.record(
                    "alert_ack",
                    f"alert_ack:{alert_id}",
                    {
                        "alert_id": alert_id,
                        "rule_id": row["rule_id"],
                        "agent_id": row["agent_id"],
                        "acknowledged_by": user_id,
                        "ts": format_ts(now),
                    },
                )
            except Exception:  # noqa: BLE001 - the console audit row is the primary record
                log.exception("alert_ack evidence record failed")
        return new


# --------------------------------------------------------------------------- routes


class InboxRoute:
    def __init__(self, notifier: Any, console_base: str = "/console") -> None:
        self.notifier = notifier
        self.base = console_base

    def send(self, alert: Mapping[str, Any]) -> str:
        subject, body = triage_text(alert, self.base)
        self.notifier.notify("alert", subject, body)
        return "sent"


class SiemRoute:
    def __init__(self, sink: Any, env: str = "") -> None:
        self.sink = sink
        self.env = env

    def send(self, alert: Mapping[str, Any]) -> str:
        if self.sink is None:
            return "off"
        from supervisor.adapters.integrations.siem import event_from_alert

        n = self.sink.emit([event_from_alert(alert, self.env)])
        return "sent" if n else "dead_letter"


class WebhookRoute:
    def __init__(self, notifier: Any) -> None:
        self.notifier = notifier

    def send(self, alert: Mapping[str, Any]) -> str:
        subject, body = triage_text(alert)
        doc = {
            "alert_id": alert["alert_id"],
            "rule_id": alert["rule_id"],
            "severity": alert["severity"],
            "agent_id": alert.get("agent_id"),
            "case_id": alert.get("case_id"),
            "window_count": alert["window_count"],
            "window_s": alert["window_s"],
            "threshold": alert["threshold"],
            "chain_lane": alert.get("chain_lane"),
            "chain_seq": alert.get("chain_seq"),
            "entry_hash": alert.get("entry_hash"),
            "subject": subject,
            "body": body,
            "ts": format_ts(alert["ts"]),
        }
        return str(self.notifier.send_json("alert", str(alert["alert_id"]), doc))


class StubRoute:
    """Pager (and ITSM) route: a ``queued`` notice, never sent (WP21 stubs)."""

    def __init__(self, notifier: Any) -> None:
        self.notifier = notifier

    def send(self, alert: Mapping[str, Any]) -> str:
        subject, body = triage_text(alert)
        self.notifier.notify("alert", subject, body)
        return "queued"


def build_routes(
    settings: Any,
    state: StateStore,
    clock: Clock,
    *,
    masker: Any = None,
    siem_sink: Any = None,
    env: str = "",
    inbox: Any = None,
) -> Routes:
    """The route table for the alert job. ``webhook`` is present only when the webhook
    notifier is really on (flag and URL); otherwise it reports ``off``."""
    from supervisor.adapters.notify import (
        InboxNotifier,
        StubNotifier,
        WebhookNotifier,
        build_notifier,
    )

    # Alert text is a fixed vocabulary plus ids and counts, so the inbox copy is not masked
    # (the regex masker would only damage hashes and ids); the webhook notifier below still
    # gets the masker for its stub path.
    inbox = inbox or InboxNotifier(state, clock, None)
    channels: dict[str, Route] = {
        "inbox": InboxRoute(inbox),
        "pager": StubRoute(StubNotifier("pager", inbox)),
    }
    if siem_sink is not None:
        channels["siem"] = SiemRoute(siem_sink, env)
    notifier, _ = build_notifier(settings, state, clock, masker)
    hook = next((t for t in notifier.targets if isinstance(t, WebhookNotifier)), None)
    if hook is not None:
        channels["webhook"] = WebhookRoute(hook)
    return Routes(channels)


__all__ = [
    "ALERT_FIELDS",
    "AlertError",
    "AlertService",
    "InboxRoute",
    "Route",
    "Routes",
    "SiemRoute",
    "StubRoute",
    "WebhookRoute",
    "build_routes",
    "triage_text",
]

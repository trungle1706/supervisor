"""Outbound events of the AI system lifecycle (WP-G1, docs/governance.md section 12).

The services write one ``outbound_event`` row when a stage is approved, a review is completed,
a system is registered or a system is archived. The payload holds ids and enums only (no name,
no text, no user id). With ``WEBHOOKS_ENABLED=1`` the webhook stub logs each undelivered event
and marks it delivered; the real HTTP sender is later work. Nothing else reads the table yet.

An event that cannot be written is logged and dropped: it never stops the change that caused it.
"""

from __future__ import annotations

import logging
import re
import uuid
from collections.abc import Mapping
from typing import Any

from supervisor.governance.model import SystemsError


def _on(value: Any) -> bool:
    if isinstance(value, str):
        return value.strip().lower() in ("1", "true")
    return bool(value)


log = logging.getLogger("supervisor.governance.events")

EVENT_KINDS: tuple[str, ...] = (
    "stage_approved",
    "review_completed",
    "system_registered",
    "system_archived",
    "governance_action",  # WP-G5: a governance action asked for a webhook
)
_SAFE = re.compile(r"^[A-Za-z0-9_.:-]{0,64}$")


def check_payload(payload: Mapping[str, Any]) -> dict[str, Any]:
    """Ids and enums only: short safe tokens and whole numbers; nothing else."""
    out: dict[str, Any] = {}
    for key, value in payload.items():
        if not isinstance(key, str) or not _SAFE.match(key):
            raise SystemsError("event payload has a bad key")
        if isinstance(value, bool) or not isinstance(value, (str, int)):
            raise SystemsError("event payload holds ids, enums and whole numbers only")
        if isinstance(value, str) and not _SAFE.match(value):
            raise SystemsError("event payload value is not an id or an enum")
        out[key] = value
    return dict(sorted(out.items()))


def emit(
    state: Any, clock: Any, settings: Any, kind: str, system_id: str, payload: Mapping[str, Any]
) -> dict[str, Any] | None:
    """Write the event row; with WEBHOOKS_ENABLED, hand it to the stub. Returns the row or None
    when it could not be written (logged)."""
    try:
        if kind not in EVENT_KINDS:
            raise SystemsError(f"event kind must be one of {', '.join(EVENT_KINDS)}")
        row = dict(
            state.insert(
                "outbound_event",
                {
                    "event_id": "ev_" + uuid.uuid4().hex[:24],
                    "kind": kind,
                    "system_id": system_id,
                    "payload": check_payload({"system_id": system_id, **payload}),
                    "created_at": clock.now(),
                    "delivered": False,
                },
            )
        )
    except Exception:  # noqa: BLE001 - an event must never stop the change that caused it
        log.exception("outbound event %s was not written", kind)
        return None
    if getattr(settings, "webhooks_enabled", False):
        try:
            deliver_pending(state, clock, settings, limit=1, only=row["event_id"])
        except Exception:  # noqa: BLE001 - a sender problem never fails the request
            log.exception("outbound event %s was not delivered", row["event_id"])
    return row


def deliver_pending(
    state: Any, clock: Any, settings: Any, limit: int = 50, only: str | None = None
) -> int:
    """With WEBHOOKS_ENABLED: send the undelivered events, oldest first, through the stub and
    mark them delivered. Without it: nothing happens (returns 0). Never raises."""
    if not getattr(settings, "webhooks_enabled", False):
        return 0
    from supervisor.adapters.notify.outbound_webhook import OutboundWebhookStub

    sender = OutboundWebhookStub()
    if only is not None:  # one event: read that row, not the table
        one = state.get("outbound_event", {"event_id": only})
        rows = [dict(one)] if one is not None and not _on(one["delivered"]) else []
    else:
        rows = [dict(r) for r in state.query("outbound_event") if not _on(r["delivered"])]
    rows.sort(key=lambda r: (r["created_at"], r["event_id"]))
    done = 0
    for row in rows[:limit]:
        try:
            if not sender.send(row):
                continue
            state.update(
                "outbound_event",
                {"event_id": row["event_id"]},
                {"delivered": True, "delivered_at": clock.now()},
                int(row["row_version"]),
            )
            done += 1
        except Exception:  # noqa: BLE001 - the event stays undelivered and is tried again
            log.exception("outbound event %s was not marked delivered", row.get("event_id"))
    return done


def list_events(state: Any, system_id: str | None = None, limit: int = 200) -> list[dict[str, Any]]:
    where = {"system_id": system_id} if system_id else None
    rows = [dict(r) for r in state.query("outbound_event", where)]
    rows.sort(key=lambda r: (r["created_at"], r["event_id"]), reverse=True)
    return rows[:limit]

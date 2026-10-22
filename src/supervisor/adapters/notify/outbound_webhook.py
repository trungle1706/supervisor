"""Outbound event webhook stub (WP-G1, ``WEBHOOKS_ENABLED``, off by default).

It logs the event (kind, system id, event id) and says it is delivered. It sends nothing: the
runtime has no network path for it. The real HTTP sender is later work; it will replace this
class behind the same ``send`` method. No import of httpx or any network library here.
"""

from __future__ import annotations

import logging
from collections.abc import Mapping
from typing import Any

log = logging.getLogger("supervisor.notify.outbound")


class OutboundWebhookStub:
    kind = "webhook-stub"

    def __init__(self) -> None:
        self.sent: list[str] = []

    def send(self, event: Mapping[str, Any]) -> bool:
        """Log one outbound event and report it as delivered. Never raises, never sends."""
        log.info(
            "outbound webhook stub: event %s (%s) for %s logged (not sent)",
            str(event.get("event_id"))[:64],
            str(event.get("kind"))[:64],
            str(event.get("system_id"))[:64],
        )
        self.sent.append(str(event.get("event_id")))
        return True

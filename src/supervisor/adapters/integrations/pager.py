"""Paging for urgent cases with acknowledgement write-back (WP11 stub, OFF by default).

Direction: Supervisor -> pager (PagerDuty / Opsgenie / the bank's on-call tool): page;
pager -> Supervisor: acknowledgement, written back as a case comment (who, when) so the
"time to human" is in the case timeline and on the evidence chain.

Contract (``docs/bank-integration.md`` section Pager):

* page when a case opens or is raised to a severity in ``page_severities`` (default
  ``critical``; a gate pause opens a case at high or above);
* page fields: dedup_key (= case_id; the pager merges repeats), severity, agent_id,
  rule_id, title (no free text), console_url, opened_at;
* acknowledgement fields: dedup_key, acked_by (pager user id), acked_at (RFC 3339 UTC);
  the comment is ``Paged: acknowledged by <user> at <ts> (<pager>)``, written in the
  name of that person (resolved to a console identity; unknown users are refused);
* auth: placeholder (``FILL-ME`` routing key from the bank vault);
* retry: ``RetryPolicy`` 3 attempts (1 s, 2 s); a failed page is reported, never blocks
  the case, and the console inbox notice is always written regardless.

``FakePager`` records pages and simulates acks for tests and the demo.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from typing import Any, Protocol

from supervisor.adapters.integrations import IntegrationError, RetryPolicy, with_retry
from supervisor.core.canonical import format_ts


@dataclass(frozen=True)
class Page:
    dedup_key: str
    severity: str
    agent_id: str
    rule_id: str | None
    title: str
    console_url: str
    opened_at: str


@dataclass(frozen=True)
class Ack:
    dedup_key: str
    acked_by: str
    acked_at: str


class PagerClient(Protocol):
    def trigger(self, page: Page) -> str: ...


@dataclass
class FakePager:
    pages: dict[str, Page] = field(default_factory=dict)
    triggers: int = 0
    fail_next: int = 0

    def trigger(self, page: Page) -> str:
        self.triggers += 1
        if self.fail_next > 0:
            self.fail_next -= 1
            raise ConnectionError("fake pager unavailable")
        self.pages.setdefault(page.dedup_key, page)  # dedup on the case id
        return page.dedup_key

    def ack(self, dedup_key: str, user: str, at: str) -> Ack:
        if dedup_key not in self.pages:
            raise IntegrationError(f"no page with dedup_key {dedup_key}")
        return Ack(dedup_key, user, at)


class PagerBridge:
    """Decide whether to page, page, and write acknowledgements back to the case."""

    def __init__(
        self,
        client: PagerClient,
        case_service: Any,
        resolve_actor: Callable[[str], Any | None],
        *,
        page_severities: tuple[str, ...] = ("critical",),
        console_base_url: str = "http://127.0.0.1:8000",
        pager_name: str = "pager",
        retry: RetryPolicy | None = None,
        sleep: Callable[[float], None] | None = None,
    ) -> None:
        self.client = client
        self.cases = case_service
        # pager user id -> console principal (kind "user", with a comment role), or None.
        # The case service accepts workflow actions from people only, so the ack comment is
        # written in the name of the person who acknowledged the page.
        self.resolve_actor = resolve_actor
        self.page_severities = page_severities
        self.base = console_base_url.rstrip("/")
        self.name = pager_name
        self.retry = retry or RetryPolicy()
        self._kw: dict[str, Any] = {"sleep": sleep} if sleep else {}
        self.paged: set[str] = set()

    def should_page(self, case: Mapping[str, Any]) -> bool:
        return case["severity"] in self.page_severities and case["case_id"] not in self.paged

    def maybe_page(self, case_id: str, rule_id: str | None = None) -> bool:
        case = self.cases.get(case_id)
        if not self.should_page(case):
            return False
        opened = case["opened_at"]
        page = Page(
            dedup_key=str(case_id),
            severity=str(case["severity"]),
            agent_id=str(case["agent_id"]),
            rule_id=rule_id,
            title=f"Supervisor {case['severity']} case {case_id} ({case['agent_id']})",
            console_url=f"{self.base}/console/cases/{case_id}",
            opened_at=format_ts(opened) if hasattr(opened, "tzinfo") else str(opened),
        )
        with_retry(lambda: self.client.trigger(page), self.retry, what="page", **self._kw)
        self.paged.add(str(case_id))
        return True

    def on_ack(self, ack: Ack) -> Mapping[str, Any]:
        """Acknowledgement from the pager -> case comment (evidence on the chain)."""
        actor = self.resolve_actor(ack.acked_by)
        if actor is None:
            raise IntegrationError(
                f"pager user {ack.acked_by} has no console identity; ack not written. "
                "Map the on-call group to a console role (SCIM)"
            )
        case = self.cases.get(ack.dedup_key)
        text = f"Paged: acknowledged by {ack.acked_by} at {ack.acked_at} ({self.name})"
        return self.cases.comment(ack.dedup_key, text, actor, case["row_version"])


__all__ = ["Ack", "FakePager", "Page", "PagerBridge", "PagerClient"]

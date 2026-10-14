"""ITSM tickets for cases (WP11 stub, OFF by default; ServiceNow / Jira on the bank side).

Direction: Supervisor -> ITSM (create, update, close); ITSM -> Supervisor only through
the write-back of the ticket number into ``cases.itsm_ref`` (``CaseService.set_itsm_ref``,
recorded on the evidence chain).

Contract (``docs/bank-integration.md`` section ITSM):

* correlation key: ``case_id`` (idempotency: a second create for the same case returns
  the existing ticket);
* create is triggered by a reviewer (the ``itsm_ref`` write-back is a workflow action and
  the case service accepts those from people only); status pushes run in the background;
* create fields: case_id, title (no free text: ``Supervisor case <id>: <severity> <agent>
  rule <rule>``), severity -> ITSM priority (``PRIORITY``), agent_id, rule_id, status,
  console_url, opened_at (RFC 3339 UTC), report_due_at (SBV 24 h clock);
* update fields: status (open | triaged | contained | closed), resolution, updated_at;
* no PII and no case free text leave the Supervisor (the ticket links to the console);
* auth: placeholder (``FILL-ME`` service account; token from the bank vault, injected
  into the client, never stored in git or logs);
* retry: ``RetryPolicy`` 3 attempts (1 s, 2 s); a failure never blocks the case workflow,
  it is reported and retried on the next sync.

``InMemoryItsm`` is the fake used by tests and the demo; a real client implements
``ItsmClient`` on the bank side.
"""

from __future__ import annotations

import itertools
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from typing import Any, Protocol

from supervisor.adapters.integrations import IntegrationError, RetryPolicy, with_retry
from supervisor.core.canonical import format_ts

PRIORITY = {"critical": "P1", "high": "P2", "medium": "P3", "low": "P4"}
STATUSES = ("open", "triaged", "contained", "closed")


@dataclass(frozen=True)
class TicketRequest:
    case_id: str
    title: str
    priority: str
    severity: str
    agent_id: str
    rule_id: str | None
    status: str
    console_url: str
    opened_at: str
    report_due_at: str | None


@dataclass(frozen=True)
class TicketUpdate:
    status: str
    resolution: str | None
    updated_at: str


class ItsmClient(Protocol):
    def create(self, req: TicketRequest) -> str: ...

    def update(self, ticket_ref: str, upd: TicketUpdate) -> None: ...


def _ts(value: Any) -> str | None:
    if value is None:
        return None
    return format_ts(value) if hasattr(value, "tzinfo") else str(value)


def ticket_request(
    case: Mapping[str, Any], *, rule_id: str | None, console_base_url: str
) -> TicketRequest:
    sev = str(case["severity"])
    title = f"Supervisor case {case['case_id']}: {sev} {case['agent_id']}" + (
        f" rule {rule_id}" if rule_id else ""
    )
    return TicketRequest(
        case_id=str(case["case_id"]),
        title=title,
        priority=PRIORITY.get(sev, "P3"),
        severity=sev,
        agent_id=str(case["agent_id"]),
        rule_id=rule_id,
        status=str(case["status"]),
        console_url=f"{console_base_url.rstrip('/')}/console/cases/{case['case_id']}",
        opened_at=_ts(case["opened_at"]) or "",
        report_due_at=_ts(case.get("report_due_at")),
    )


@dataclass
class InMemoryItsm:
    """Fake ITSM. ``fail_next`` makes the next N calls raise ConnectionError (retry tests)."""

    tickets: dict[str, dict[str, Any]] = field(default_factory=dict)
    by_case: dict[str, str] = field(default_factory=dict)
    fail_next: int = 0
    calls: int = 0
    _ids: Any = field(default_factory=lambda: itertools.count(1001))

    def _maybe_fail(self) -> None:
        self.calls += 1
        if self.fail_next > 0:
            self.fail_next -= 1
            raise ConnectionError("fake ITSM unavailable")

    def create(self, req: TicketRequest) -> str:
        self._maybe_fail()
        if req.case_id in self.by_case:  # idempotent on the correlation key
            return self.by_case[req.case_id]
        ref = f"INC{next(self._ids):07d}"
        self.tickets[ref] = {**req.__dict__, "history": []}
        self.by_case[req.case_id] = ref
        return ref

    def update(self, ticket_ref: str, upd: TicketUpdate) -> None:
        self._maybe_fail()
        if ticket_ref not in self.tickets:
            raise IntegrationError(f"unknown ticket {ticket_ref}")
        if upd.status not in STATUSES:
            raise IntegrationError(f"unknown status {upd.status!r}")
        t = self.tickets[ticket_ref]
        t["history"].append(upd.__dict__)
        t["status"] = upd.status


class ItsmSync:
    """Push case state to the ITSM; write the ticket number back to the case."""

    def __init__(
        self,
        client: ItsmClient,
        case_service: Any,
        *,
        console_base_url: str = "http://127.0.0.1:8000",
        retry: RetryPolicy | None = None,
        sleep: Callable[[float], None] | None = None,
    ) -> None:
        self.client = client
        self.cases = case_service
        self.base = console_base_url
        self.retry = retry or RetryPolicy()
        self._kw: dict[str, Any] = {"sleep": sleep} if sleep else {}
        self.pushed_status: dict[str, str] = {}

    def _rule_of(self, case_id: str) -> str | None:
        for v in self.cases.linked_verdicts(case_id):
            if v.get("rule_id"):
                return str(v["rule_id"])
        return None

    def sync_case(self, case_id: str, actor: Any = None) -> str:
        """Create the ticket (once) or push the status. Returns the ticket ref.

        Creating a ticket writes ``itsm_ref`` back to the case, which is a workflow action:
        the case service accepts it only from a signed-in person with a workflow role
        (``actor``: the reviewer who pressed "Create ticket"). A status push needs no actor."""
        case = self.cases.get(case_id)
        ref = case.get("itsm_ref")
        if not ref:
            if actor is None:
                raise IntegrationError(
                    f"case {case_id} has no ITSM ticket yet; creating one needs the reviewer "
                    "who asks for it (the write-back of itsm_ref is a workflow action)"
                )
            req = ticket_request(case, rule_id=self._rule_of(case_id), console_base_url=self.base)
            ref = with_retry(
                lambda: self.client.create(req), self.retry, what="ITSM create", **self._kw
            )
            case = self.cases.set_itsm_ref(case_id, ref, actor, case["row_version"])
            self.pushed_status[case_id] = str(case["status"])
            return str(ref)
        status = str(case["status"])
        if self.pushed_status.get(case_id) != status:
            upd = TicketUpdate(
                status=status,
                resolution=case.get("resolution"),
                updated_at=_ts(self.cases.clock.now()) or "",
            )
            with_retry(
                lambda: self.client.update(str(ref), upd),
                self.retry,
                what="ITSM update",
                **self._kw,
            )
            self.pushed_status[case_id] = status
        return str(ref)


__all__ = [
    "PRIORITY",
    "InMemoryItsm",
    "ItsmClient",
    "ItsmSync",
    "TicketRequest",
    "TicketUpdate",
    "ticket_request",
]

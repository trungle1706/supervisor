"""SIEM events (WP11 stub, OFF by default): gate decisions, cases, chain anchors.

Direction: Supervisor -> bank SIEM (Splunk HEC, Sentinel, QRadar...). One-way.

Source: the evidence chain (``chain_entry`` + ``chain_payload``), read with a cursor per
lane (``ChainEventFeed``). The chain payloads already hold no PII (hashes and masked
excerpts only), and the SIEM event keeps a subset of their fields: ids, rule ids,
actions, hashes. Free text never leaves (only its SHA-256, when the chain has it).

Event schema ``supervisor.siem.v1`` (JSON, one object per line; same fields in CEF):

========================  ======================================================
Field                     Meaning
========================  ======================================================
schema                    ``supervisor.siem.v1``
event_id                  ``<lane>:<seq>`` of the chain entry (unique, idempotent)
event_type                gate_decision | gate_state_change | case_opened |
                          case_event | chain_root | chain_anchor
ts                        RFC 3339 UTC of the chain entry
severity                  0..10 (CEF scale); see ``SEVERITY``
outcome                   allow | block | pause | alert | resume | open | ... | sealed
agent_id                  agent id, or null for root / anchor events
rule_id                   Tier 0 rule id, or null
case_id                   case id, or null
actor                     user id / ``rule:<id>`` / ``supervisor-system``, or null
chain_lane, chain_seq     where the evidence is
entry_hash                SHA-256 of the chain entry (verifiable offline)
env                       ``laptop`` | ``databricks_app`` | ...
product, vendor, version  ``Supervisor``, ``Supervisor``, package version
========================  ======================================================

Sinks: ``LogSiemSink`` (append to a local file the bank's forwarder tails; the default
when enabled) and ``WebhookSiemSink`` (HEC-style POST; off unless SIEM_SINK=webhook and
the URL is filled; bounded retry). ``build_siem_sink`` returns None when SIEM is off.
"""

from __future__ import annotations

import json
import threading
from collections.abc import Callable, Iterable, Mapping
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Protocol

from supervisor import __version__
from supervisor.adapters.integrations import (
    IntegrationError,
    IntegrationSettings,
    RetryPolicy,
    is_placeholder,
    with_retry,
)
from supervisor.core.canonical import canonical_json, format_ts
from supervisor.core.ports import TableStore

SCHEMA = "supervisor.siem.v1"
VENDOR = "Supervisor"
PRODUCT = "Supervisor"

# CEF severity 0..10
SEVERITY = {
    "allow": 1,
    "alert": 5,
    "block": 7,
    "pause": 8,
    "quarantine": 9,
    "resume": 5,
    "release": 5,
    "low": 3,
    "medium": 5,
    "high": 8,
    "critical": 10,
    "sealed": 1,
    "anchored": 1,
}
EVENT_TYPES = (
    "gate_decision",
    "gate_state_change",
    "case_opened",
    "case_event",
    "chain_root",
    "chain_anchor",
)
RECORD_TO_EVENT = {
    "gate_decision": "gate_decision",
    "gate_state_change": "gate_state_change",
    "case": "case_opened",
    "case_event": "case_event",
    "root_commit": "chain_root",
}


@dataclass(frozen=True)
class SiemEvent:
    event_id: str
    event_type: str
    ts: str
    severity: int
    outcome: str
    agent_id: str | None
    rule_id: str | None
    case_id: str | None
    actor: str | None
    chain_lane: str | None
    chain_seq: int | None
    entry_hash: str | None
    env: str
    schema: str = SCHEMA
    product: str = PRODUCT
    vendor: str = VENDOR
    version: str = __version__

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


def _ts(value: Any) -> str:
    return format_ts(value) if isinstance(value, datetime) else str(value)


def event_from_chain(entry: Mapping[str, Any], payload: Mapping[str, Any]) -> SiemEvent | None:
    """Map one chain entry + its payload to a SIEM event. None for record types the SIEM
    does not need (registry rows, judge verdicts, tier 0b notes)."""
    etype = RECORD_TO_EVENT.get(str(entry["record_type"]))
    if etype is None:
        return None
    p = payload
    if etype == "gate_decision":
        outcome = str(p.get("action") or ("allow" if p.get("allow") else "block"))
        sev = SEVERITY.get(outcome, 5)
        actor = None
    elif etype == "gate_state_change":
        outcome = str(p.get("event") or "state_change")
        sev = SEVERITY.get(outcome, 5)
        actor = p.get("principal")
    elif etype == "case_opened":
        outcome = "open"
        sev = SEVERITY.get(str(p.get("severity")), 5)
        actor = p.get("opened_by")
    elif etype == "case_event":
        outcome = str(p.get("action") or "case_event")
        sev = SEVERITY.get(str(p.get("severity")), 3)
        actor = p.get("actor")
    else:  # chain_root
        outcome, sev, actor = "sealed", SEVERITY["sealed"], None
    return SiemEvent(
        event_id=f"{entry['lane']}:{entry['seq']}",
        event_type=etype,
        ts=_ts(entry["ts"]),
        severity=int(sev),
        outcome=outcome,
        agent_id=p.get("agent_id"),
        rule_id=p.get("rule_id"),
        case_id=p.get("case_id"),
        actor=str(actor) if actor else None,
        chain_lane=str(entry["lane"]),
        chain_seq=int(entry["seq"]),
        entry_hash=str(entry["entry_hash"]),
        env=str(entry.get("env") or ""),
    )


def event_from_anchor(row: Mapping[str, Any], env: str = "") -> SiemEvent:
    """An ``anchor`` row (signed head written to the WORM / UC volume target)."""
    return SiemEvent(
        event_id=f"anchor:{row['anchor_id']}",
        event_type="chain_anchor",
        ts=_ts(row["anchored_at"]),
        severity=SEVERITY["anchored"],
        outcome="anchored",
        agent_id=None,
        rule_id=None,
        case_id=None,
        actor=None,
        chain_lane=str(row.get("lane") or "root"),
        chain_seq=int(row["seq_to"]) if row.get("seq_to") is not None else None,
        entry_hash=str(row.get("root_hash") or ""),
        env=env,
    )


# --------------------------------------------------------------------------- formats


def to_json(event: SiemEvent) -> str:
    """Canonical JSON (sorted keys, UTF-8), one line."""
    return canonical_json(event.as_dict())


def _cef_header(value: Any) -> str:
    return str(value).replace("\\", "\\\\").replace("|", "\\|").replace("\n", " ")


def _cef_ext(value: Any) -> str:
    return (
        str(value)
        .replace("\\", "\\\\")
        .replace("=", "\\=")
        .replace("\r", "\\r")
        .replace("\n", "\\n")
    )


# CEF extension keys: standard keys where one fits, custom strings (cs1..cs6) otherwise.
CEF_EXT = (
    ("rt", "ts"),
    ("outcome", "outcome"),
    ("suser", "actor"),
    ("externalId", "event_id"),
    ("cs1Label", None),
    ("cs1", "agent_id"),
    ("cs2Label", None),
    ("cs2", "rule_id"),
    ("cs3Label", None),
    ("cs3", "case_id"),
    ("cs4Label", None),
    ("cs4", "chain_lane"),
    ("cn1Label", None),
    ("cn1", "chain_seq"),
    ("cs5Label", None),
    ("cs5", "entry_hash"),
    ("cs6Label", None),
    ("cs6", "env"),
)
CEF_LABELS = {
    "cs1Label": "agentId",
    "cs2Label": "ruleId",
    "cs3Label": "caseId",
    "cs4Label": "chainLane",
    "cn1Label": "chainSeq",
    "cs5Label": "entryHash",
    "cs6Label": "env",
}


def to_cef(event: SiemEvent) -> str:
    """ArcSight CEF:0 line. Header fields escape | and \\; extensions escape = and \\."""
    d = event.as_dict()
    header = "|".join(
        _cef_header(x)
        for x in (
            "CEF:0",
            event.vendor,
            event.product,
            event.version,
            f"{event.schema}:{event.event_type}",
            event.event_type.replace("_", " "),
            event.severity,
        )
    )
    parts = []
    for key, field in CEF_EXT:
        value = CEF_LABELS[key] if field is None else d.get(field)
        if value is None or value == "":
            continue
        parts.append(f"{key}={_cef_ext(value)}")
    return header + "|" + " ".join(parts)


FORMATTERS: dict[str, Callable[[SiemEvent], str]] = {"json": to_json, "cef": to_cef}


# --------------------------------------------------------------------------- sinks


class SiemSink(Protocol):
    def emit(self, events: Iterable[SiemEvent]) -> int: ...


class LogSiemSink:
    """Append one line per event to a local file. The bank's log forwarder (Splunk UF,
    AMA, ...) tails it. No network from the Supervisor process."""

    def __init__(self, path: Path, fmt: str = "json") -> None:
        if fmt not in FORMATTERS:
            raise IntegrationError(f"SIEM_FORMAT must be json or cef, not {fmt!r}")
        self.path = Path(path)
        self.fmt = fmt
        self._lock = threading.Lock()

    def emit(self, events: Iterable[SiemEvent]) -> int:
        lines = [FORMATTERS[self.fmt](e) for e in events]
        if not lines:
            return 0
        with self._lock:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with self.path.open("a", encoding="utf-8", newline="\n") as fh:
                fh.write("".join(line + "\n" for line in lines))
        return len(lines)


Transport = Callable[[str, dict[str, Any], float], Mapping[str, Any]]


class WebhookSiemSink:
    """HEC-style POST of a batch (``{"events": [...]}``). OFF by default.

    Auth: placeholder. The bank owner supplies the token through the bank vault into the
    transport (header ``Authorization: Splunk <token>`` or the Sentinel equivalent); it is
    never read from git or logged. Retry: ``RetryPolicy`` (3 attempts, 1 s, 2 s)."""

    def __init__(
        self,
        url: str,
        *,
        transport: Transport | None = None,
        retry: RetryPolicy | None = None,
        timeout_s: float = 10.0,
        sleep: Callable[[float], None] | None = None,
    ) -> None:
        if is_placeholder(url):
            raise IntegrationError("SIEM_WEBHOOK_URL is empty or FILL-ME; SIEM webhook is off")
        self.url = url
        self.transport = transport or _default_transport
        self.retry = retry or RetryPolicy()
        self.timeout_s = timeout_s
        self._sleep = sleep

    def emit(self, events: Iterable[SiemEvent]) -> int:
        batch = [e.as_dict() for e in events]
        if not batch:
            return 0
        kw: dict[str, Any] = {"what": "SIEM webhook"}
        if self._sleep is not None:
            kw["sleep"] = self._sleep
        with_retry(
            lambda: self.transport(self.url, {"events": batch}, self.timeout_s), self.retry, **kw
        )
        return len(batch)


def _default_transport(url: str, payload: dict[str, Any], timeout_s: float) -> Mapping[str, Any]:
    from supervisor.adapters.http_json import post_json

    return post_json(url, payload, timeout_s)


def build_siem_sink(cfg: IntegrationSettings, data_dir: Path) -> SiemSink | None:
    """None when SIEM is off (the default)."""
    if not cfg.siem_enabled:
        return None
    if cfg.siem_sink == "webhook":
        return WebhookSiemSink(cfg.siem_webhook_url)
    path = cfg.siem_file_path or Path(data_dir) / "siem" / "events.log"
    return LogSiemSink(path, cfg.siem_format)


# --------------------------------------------------------------------------- feed


class ChainEventFeed:
    """Reads new chain entries (cursor = last seq per lane) and emits SIEM events.

    Idempotent per cursor: the caller stores ``cursor`` (e.g. a state row) and passes it
    back. ``event_id`` = ``<lane>:<seq>`` lets the SIEM drop duplicates after a crash."""

    def __init__(self, tables: TableStore, sink: SiemSink) -> None:
        self.tables = tables
        self.sink = sink
        self.cursor: dict[str, int] = {}
        self._anchors_seen: set[str] = set()

    def poll(self) -> int:
        events: list[SiemEvent] = []
        for entry in self.tables.query("chain_entry", order_by=["lane", "seq"]):
            lane, seq = str(entry["lane"]), int(entry["seq"])
            if seq <= self.cursor.get(lane, -1):
                continue
            rows = self.tables.query("chain_payload", {"lane": lane, "seq": seq})
            payload = json.loads(rows[0]["payload"]) if rows else {}
            ev = event_from_chain(entry, payload)
            if ev is not None:
                events.append(ev)
            self.cursor[lane] = seq
        for row in self.tables.query("anchor"):
            if row["anchor_id"] in self._anchors_seen:
                continue
            self._anchors_seen.add(str(row["anchor_id"]))
            events.append(event_from_anchor(row))
        events.sort(key=lambda e: (e.ts, e.event_id))
        return self.sink.emit(events)


__all__ = [
    "EVENT_TYPES",
    "SCHEMA",
    "SEVERITY",
    "ChainEventFeed",
    "LogSiemSink",
    "SiemEvent",
    "SiemSink",
    "WebhookSiemSink",
    "build_siem_sink",
    "event_from_anchor",
    "event_from_chain",
    "to_cef",
    "to_json",
]

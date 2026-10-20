"""SIEM export (WP11 schema, WP21 production sinks; OFF by default).

Direction: Supervisor -> bank SIEM (Splunk HEC, Sentinel, QRadar, a Databricks-hosted SIEM
connector...). One-way. Events: gate decisions, state changes, cases, chain anomalies,
ingress rejections, alerts, chain roots and anchors.

Source: the evidence chain (``chain_entry`` + ``chain_payload``), read with a cursor per
lane (``ChainEventFeed``), plus ``alert`` rows pushed by the alert job. The chain payloads
already hold no PII (hashes and masked excerpts only), and the SIEM event keeps a subset of
their fields: ids, rule ids, actions, hashes. Free text never leaves (only its SHA-256, when
the chain has it).

Event schema ``supervisor.siem.v1`` (JSON, one object per line; same fields in CEF):

========================  ======================================================
Field                     Meaning
========================  ======================================================
schema                    ``supervisor.siem.v1``
event_id                  ``<lane>:<seq>`` of the chain entry (unique, idempotent)
event_type                gate_decision | gate_state_change | case_opened |
                          case_event | chain_root | chain_anchor | alert |
                          ingress_reject | chain_anomaly
ts                        RFC 3339 UTC of the chain entry
severity                  0..10 (CEF scale); see ``SEVERITY``
outcome                   allow | block | pause | alert | resume | open | ... | sealed
agent_id                  agent id, or null for root / anchor events
rule_id                   Tier 0 rule id (alerts: alert rule id), or null
case_id                   case id, or null
actor                     user id / ``rule:<id>`` / ``supervisor-system``, or null
chain_lane, chain_seq     where the evidence is
entry_hash                SHA-256 of the chain entry (verifiable offline)
env                       ``laptop`` | ``databricks_app`` | ...
product, vendor, version  ``Supervisor``, ``Supervisor``, package version
attrs                     small integer / enum details, or null
========================  ======================================================

Formats (``SIEM_FORMAT``): ``jsonl`` (this schema; ``json`` is an alias), ``cef`` (ArcSight
line) and ``ocsf`` (OCSF 1.x document, ``ocsf.py``). Field mapping tables: ``docs/siem.md``.

Sinks (``SIEM_SINK``): ``file`` (``LogSiemSink``: append to a local file the bank's forwarder
tails, size-based rotation), ``http`` (``WebhookSiemSink``: HEC-style POST, bounded retry
with backoff, dead-letter file, idempotency key per batch; off unless the URL is filled) and
``delta`` (``DeltaSiemSink``: append to the ``siem_event`` table through the SQL adapter).
``build_siem_sink`` returns None when SIEM is off. ``ChainEventFeed`` keeps one cursor per
chain lane in ``monitor_state`` so a restart does not send an event twice.
"""

from __future__ import annotations

import json
import os
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
from supervisor.adapters.integrations.deadletter import DeadLetter
from supervisor.adapters.integrations.ocsf import to_ocsf_dict, to_ocsf_json
from supervisor.adapters.integrations.transport import (
    HttpTransport,
    Transport,
    idempotency_key,
)
from supervisor.core.canonical import canonical_json, format_ts
from supervisor.core.errors import ConcurrencyError, DuplicateKeyError
from supervisor.core.ports import StateStore, TableStore

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
    "reject": 6,
    "verify_failed": 10,
    "verify_ok": 1,
}
EVENT_TYPES = (
    "gate_decision",
    "gate_state_change",
    "case_opened",
    "case_event",
    "chain_root",
    "chain_anchor",
    "alert",
    "ingress_reject",
    "chain_anomaly",
)
RECORD_TO_EVENT = {
    "gate_decision": "gate_decision",
    "gate_state_change": "gate_state_change",
    "case": "case_opened",
    "case_opened": "case_opened",
    "case_event": "case_event",
    "root_commit": "chain_root",
    "ingress_reject": "ingress_reject",  # WP20 ingress auth: payload agent_id, reason_code
    "chain_verify": "chain_anomaly",  # payload ok (bool), failures (int)
    "audit_pack_built": "chain_anomaly",  # payload verify_ok (bool); only a failure is sent
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
    # WP21: small integer / enum details (alerts: window_count, threshold, ...). Never free text.
    attrs: Mapping[str, Any] | None = None

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
    attrs: dict[str, Any] | None = None
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
    elif etype == "ingress_reject":
        outcome, sev, actor = "reject", SEVERITY["reject"], None
        attrs = {"reason_code": str(p.get("reason_code") or "unknown")[:64]}
    elif etype == "chain_anomaly":
        ok = p["ok"] if "ok" in p else p.get("verify_ok")
        if str(entry["record_type"]) == "audit_pack_built" and ok:
            return None  # a good audit pack is not an anomaly
        outcome = "verify_ok" if ok else "verify_failed"
        sev, actor = SEVERITY[outcome], None
        if isinstance(p.get("failures"), int):
            attrs = {"failures": int(p["failures"])}
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
        attrs=attrs,
    )


def event_from_alert(row: Mapping[str, Any], env: str = "") -> SiemEvent:
    """An ``alert`` row (rule engine, WP21). Ids, counts and enums only."""
    return SiemEvent(
        event_id=f"alert:{row['alert_id']}",
        event_type="alert",
        ts=_ts(row["ts"]),
        severity=int(SEVERITY.get(str(row["severity"]), 5)),
        outcome="open",
        agent_id=row.get("agent_id"),
        rule_id=str(row["rule_id"]),
        case_id=row.get("case_id"),
        actor="supervisor-system",
        chain_lane=row.get("chain_lane"),
        chain_seq=int(row["chain_seq"]) if row.get("chain_seq") is not None else None,
        entry_hash=row.get("entry_hash"),
        env=env,
        attrs={
            "alert_id": str(row["alert_id"]),
            "severity_label": str(row["severity"]),
            "window_s": int(row["window_s"]),
            "window_count": int(row["window_count"]),
            "threshold": int(row["threshold"]),
            "suppressed_count": int(row.get("suppressed_count") or 0),
            "dedupe_key": str(row["dedupe_key"]),
        },
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
# cn2 / cn3 carry the alert window count and the suppressed repeat count (attrs).
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
    ("cn2Label", None),
    ("cn2", "attrs.window_count"),
    ("cn3Label", None),
    ("cn3", "attrs.suppressed_count"),
)
CEF_LABELS = {
    "cs1Label": "agentId",
    "cs2Label": "ruleId",
    "cs3Label": "caseId",
    "cs4Label": "chainLane",
    "cn1Label": "chainSeq",
    "cs5Label": "entryHash",
    "cs6Label": "env",
    "cn2Label": "windowCount",
    "cn3Label": "suppressedCount",
}


def _cef_value(d: Mapping[str, Any], field: str) -> Any:
    if field.startswith("attrs."):
        return (d.get("attrs") or {}).get(field[6:])
    return d.get(field)


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
    values = {key: _cef_value(d, f) for key, f in CEF_EXT if f is not None}
    parts = []
    for key, field in CEF_EXT:
        if field is None:
            value_key = key[: -len("Label")]
            if values.get(value_key) in (None, ""):
                continue  # a label only when its value is there
            value: Any = CEF_LABELS[key]
        else:
            value = values[key]
        if value is None or value == "":
            continue
        parts.append(f"{key}={_cef_ext(value)}")
    return header + "|" + " ".join(parts)


FORMATTERS: dict[str, Callable[[SiemEvent], str]] = {
    "json": to_json,
    "jsonl": to_json,
    "cef": to_cef,
    "ocsf": to_ocsf_json,
}
FORMATS = tuple(FORMATTERS)


def check_format(fmt: str) -> str:
    if fmt not in FORMATTERS:
        raise IntegrationError(f"SIEM_FORMAT must be jsonl, cef or ocsf, not {fmt!r}")
    return fmt


def render_obj(event: SiemEvent, fmt: str) -> Any:
    """The event as it goes into an HTTP batch: a dict (jsonl, ocsf) or a string (cef)."""
    if fmt == "ocsf":
        return to_ocsf_dict(event)
    if fmt == "cef":
        return to_cef(event)
    return event.as_dict()


# --------------------------------------------------------------------------- sinks


class SiemSink(Protocol):
    def emit(self, events: Iterable[SiemEvent]) -> int: ...


class LogSiemSink:
    """Append one line per event to a local file. The bank's log forwarder (Splunk UF,
    AMA, ...) tails it. No network from the Supervisor process.

    Rotation (``max_bytes`` > 0): before a write that would pass the limit, ``events.log``
    becomes ``events.log.1``, ``.1`` becomes ``.2`` and so on up to ``backups``; the oldest
    is deleted. A forwarder that follows file names (``events.log*``) sees no gap, because
    the rename happens between two whole batches, never inside one."""

    def __init__(
        self, path: Path, fmt: str = "jsonl", *, max_bytes: int = 0, backups: int = 5
    ) -> None:
        self.path = Path(path)
        self.fmt = check_format(fmt)
        self.max_bytes = max(0, int(max_bytes))
        self.backups = max(0, int(backups))
        self._lock = threading.Lock()

    def _rotate(self) -> None:
        if self.backups == 0:
            self.path.unlink(missing_ok=True)  # keep nothing: truncate by removal
            return
        oldest = self.path.with_name(f"{self.path.name}.{self.backups}")
        oldest.unlink(missing_ok=True)
        for i in range(self.backups - 1, 0, -1):
            src = self.path.with_name(f"{self.path.name}.{i}")
            if src.exists():
                os.replace(src, self.path.with_name(f"{self.path.name}.{i + 1}"))
        os.replace(self.path, self.path.with_name(f"{self.path.name}.1"))

    def emit(self, events: Iterable[SiemEvent]) -> int:
        lines = [FORMATTERS[self.fmt](e) for e in events]
        if not lines:
            return 0
        data = "".join(line + "\n" for line in lines).encode("utf-8")
        with self._lock:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            if self.max_bytes and self.path.exists():
                if self.path.stat().st_size + len(data) > self.max_bytes:
                    if self.path.stat().st_size > 0:
                        self._rotate()
            with self.path.open("ab") as fh:
                fh.write(data)
        return len(lines)


class WebhookSiemSink:
    """HEC-style POST of a batch (``{"events": [...], "idempotency_key": "..."}``). OFF by
    default (needs a filled URL).

    Auth: placeholder. The bank owner supplies the token through the bank vault
    (``SIEM_HTTP_TOKEN``); it is never read from the repo or logged. Retry: ``RetryPolicy``
    (3 attempts, 1 s, 2 s). When all attempts fail and a dead-letter file is set, the batch is
    appended there and ``emit`` returns 0 (the feed moves on; ``replay_dead_letter`` sends
    the batches later). Without a dead-letter file the failure raises ``IntegrationError``.
    The key (SHA-256 of the event ids) is in the body and in the ``Idempotency-Key`` header."""

    def __init__(
        self,
        url: str,
        *,
        transport: Transport | None = None,
        retry: RetryPolicy | None = None,
        timeout_s: float = 10.0,
        sleep: Callable[[float], None] | None = None,
        fmt: str = "jsonl",
        dead_letter: DeadLetter | None = None,
    ) -> None:
        if is_placeholder(url):
            raise IntegrationError("SIEM_WEBHOOK_URL is empty or FILL-ME; SIEM webhook is off")
        self.url = url
        self.transport = transport or HttpTransport()
        self.retry = retry or RetryPolicy()
        self.timeout_s = timeout_s
        self._sleep = sleep
        self.fmt = check_format(fmt)
        self.dead_letter = dead_letter
        self.dead_lettered = 0  # batches parked in the dead-letter file by this sink

    def _send(self, body: dict[str, Any]) -> None:
        kw: dict[str, Any] = {"what": "SIEM webhook"}
        if self._sleep is not None:
            kw["sleep"] = self._sleep
        with_retry(lambda: self.transport(self.url, body, self.timeout_s), self.retry, **kw)

    def emit(self, events: Iterable[SiemEvent]) -> int:
        evs = list(events)
        if not evs:
            return 0
        body = {
            "events": [render_obj(e, self.fmt) for e in evs],
            "format": self.fmt,
            "idempotency_key": idempotency_key(e.event_id for e in evs),
        }
        try:
            self._send(body)
        except IntegrationError as exc:
            if self.dead_letter is None:
                raise
            self.dead_letter.put(
                "siem", body["idempotency_key"], body, str(exc), self.retry.attempts
            )
            self.dead_lettered += 1
            return 0
        return len(evs)

    def replay_dead_letter(self) -> tuple[int, int]:
        """Send the parked batches again (one try each, with the normal retry). Returns
        (sent, still_failing)."""
        if self.dead_letter is None:
            return 0, 0
        return self.dead_letter.replay(lambda e: self._send(e["payload"]))


class DeltaSiemSink:
    """Append events to the ``siem_event`` table through the SQL adapter (WP21).

    On Databricks the table is a Delta table in the configured schema: a SIEM connector that
    reads Delta, or Lakehouse Monitoring, reads it from there. The primary key ``event_id`` is
    the idempotency key: ``TableStore.append`` is an insert-only MERGE on Delta, so a second
    send of the same event adds nothing. Each row carries the OCSF document, always."""

    def __init__(self, tables: TableStore) -> None:
        self.tables = tables

    @staticmethod
    def row(event: SiemEvent) -> dict[str, Any]:
        doc = to_ocsf_dict(event)
        return {
            "event_id": event.event_id,
            "ts": datetime.fromisoformat(event.ts.replace("Z", "+00:00")),
            "event_type": event.event_type,
            "severity": event.severity,
            "outcome": event.outcome,
            "agent_id": event.agent_id,
            "rule_id": event.rule_id,
            "case_id": event.case_id,
            "actor": event.actor,
            "chain_lane": event.chain_lane,
            "chain_seq": event.chain_seq,
            "entry_hash": event.entry_hash,
            "env": event.env,
            "event_schema": event.schema,
            "ocsf_class_uid": int(doc["class_uid"]),
            "ocsf_json": canonical_json(doc),
        }

    def emit(self, events: Iterable[SiemEvent]) -> int:
        rows = [self.row(e) for e in events]
        if not rows:
            return 0
        try:
            return int(self.tables.append("siem_event", rows))
        except DuplicateKeyError:
            # Some of the rows are already there (a restart after a partial send). SQLite
            # rejects the whole statement; send row by row and skip the known ones.
            n = 0
            for r in rows:
                try:
                    n += int(self.tables.append("siem_event", [r]))
                except DuplicateKeyError:
                    continue
            return n


def build_siem_sink(
    cfg: IntegrationSettings, data_dir: Path, tables: TableStore | None = None
) -> SiemSink | None:
    """None when SIEM is off (the default). ``tables`` is needed for ``delta``."""
    if not cfg.siem_enabled:
        return None
    fmt = check_format(cfg.siem_format)
    if cfg.siem_sink in ("http", "webhook"):
        dl_path = cfg.siem_dead_letter_path or Path(data_dir) / "siem" / "dead_letter.jsonl"
        token = cfg.siem_http_token.get_secret_value() if cfg.siem_http_token else None
        return WebhookSiemSink(
            cfg.siem_webhook_url,
            transport=HttpTransport(token, cfg.siem_http_auth_scheme),
            fmt=fmt,
            dead_letter=DeadLetter(dl_path),
        )
    if cfg.siem_sink == "delta":
        if tables is None:
            raise IntegrationError("SIEM_SINK=delta needs the SQL store (no store was given)")
        return DeltaSiemSink(tables)
    path = cfg.siem_file_path or Path(data_dir) / "siem" / "events.log"
    return LogSiemSink(path, fmt, max_bytes=cfg.siem_file_max_bytes, backups=cfg.siem_file_backups)


# --------------------------------------------------------------------------- feed

MONITOR = "siem"
MAX_EVENTS_PER_POLL = 2000


class ChainEventFeed:
    """Reads new chain entries (cursor = last seq per lane) and emits SIEM events.

    With a ``state`` store the cursor of each lane (and of the anchors) lives in
    ``monitor_state`` (monitor ``siem``) and is saved only after the sink accepted the batch,
    so a restart neither loses nor repeats events. Without ``state`` the cursor is in memory
    (tests, one-shot use). ``event_id`` = ``<lane>:<seq>`` lets the SIEM drop duplicates
    after a crash between the send and the save."""

    def __init__(
        self,
        tables: TableStore,
        sink: SiemSink,
        state: StateStore | None = None,
        *,
        max_events: int = MAX_EVENTS_PER_POLL,
    ) -> None:
        self.tables = tables
        self.sink = sink
        self.state = state
        self.max_events = max_events
        self.cursor: dict[str, int] = {}
        self.anchor_cursor: tuple[str, str] = ("", "")  # (anchored_at, anchor_id) seen so far
        self._loaded = False

    # -- cursor persistence ----------------------------------------------------------
    def _load(self) -> None:
        if self._loaded or self.state is None:
            self._loaded = True
            return
        for row in self.state.query("monitor_state", {"monitor": MONITOR}):
            key, value = str(row["state_key"]), row["value"]
            if isinstance(value, str):
                value = json.loads(value)
            if key.startswith("cursor:"):
                self.cursor[key[7:]] = int(value["seq"])
            elif key == "anchor":
                self.anchor_cursor = (str(value["ts"]), str(value["id"]))
        self._loaded = True

    def _save(self, key: str, value: dict[str, Any]) -> None:
        if self.state is None:
            return
        where = {"monitor": MONITOR, "state_key": key}
        for _ in range(3):
            row = self.state.get("monitor_state", where)
            try:
                if row is None:
                    self.state.insert("monitor_state", {**where, "value": value})
                else:
                    self.state.update("monitor_state", where, {"value": value}, row["row_version"])
                return
            except (DuplicateKeyError, ConcurrencyError):
                continue
        raise IntegrationError(f"SIEM cursor {key} could not be saved")

    # -- poll --------------------------------------------------------------------------
    def poll(self) -> int:
        self._load()
        events: list[SiemEvent] = []
        new_cursor = dict(self.cursor)
        full = False
        for entry in self.tables.query("chain_entry", order_by=["lane", "seq"]):
            lane, seq = str(entry["lane"]), int(entry["seq"])
            if seq <= new_cursor.get(lane, -1):
                continue
            if len(events) >= self.max_events:
                full = True
                break
            rows = self.tables.query("chain_payload", {"lane": lane, "seq": seq})
            payload = json.loads(rows[0]["payload"]) if rows else {}
            ev = event_from_chain(entry, payload)
            if ev is not None:
                events.append(ev)
            new_cursor[lane] = seq
        new_anchor = self.anchor_cursor
        if not full:
            anchors = sorted(
                self.tables.query("anchor"),
                key=lambda r: (_ts(r["anchored_at"]), str(r["anchor_id"])),
            )
            for row in anchors:
                mark = (_ts(row["anchored_at"]), str(row["anchor_id"]))
                if mark <= self.anchor_cursor:
                    continue
                events.append(event_from_anchor(row))
                new_anchor = max(new_anchor, mark)
        events.sort(key=lambda e: (e.ts, e.event_id))
        n = self.sink.emit(events)  # raises -> nothing is saved, the next poll resends
        for lane, seq in new_cursor.items():
            if self.cursor.get(lane) != seq:
                self._save(f"cursor:{lane}", {"seq": seq})
        if new_anchor != self.anchor_cursor:
            self._save("anchor", {"ts": new_anchor[0], "id": new_anchor[1]})
        self.cursor = new_cursor
        self.anchor_cursor = new_anchor
        return n


__all__ = [
    "EVENT_TYPES",
    "FORMATS",
    "SCHEMA",
    "SEVERITY",
    "ChainEventFeed",
    "DeltaSiemSink",
    "HttpTransport",
    "LogSiemSink",
    "SiemEvent",
    "SiemSink",
    "WebhookSiemSink",
    "build_siem_sink",
    "event_from_alert",
    "event_from_anchor",
    "event_from_chain",
    "idempotency_key",
    "render_obj",
    "to_cef",
    "to_json",
]

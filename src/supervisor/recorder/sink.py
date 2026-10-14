"""Write normalised events to the TableStore; spool to JSONL when the store fails.

* Idempotent by ``event_id``: rows already in ``agent_event`` (or twice in one batch) are
  skipped, not errors. The OTLP receiver, the in-process exporter and the ingest job all
  write through here, so a span seen on two paths is stored once.
* Spool line format (one JSON object per line, UTF-8), see ``docs/recorder.md``::

    {"kind": "rows", "agent_event": [...], "agent_event_raw": [...]}   # normalised rows
    {"kind": "otlp", "payload": {...ExportTraceServiceRequest...}}     # not yet normalised

  Rows in the spool are already masked per capture level; timestamps are RFC 3339 strings.
"""

from __future__ import annotations

import json
import os
import threading
import uuid
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from supervisor.core.canonical import format_ts, parse_ts
from supervisor.core.errors import DuplicateKeyError
from supervisor.core.models import AgentEvent
from supervisor.core.ports import TableStore
from supervisor.recorder.normalise import Normalised

EVENT_TABLE = "agent_event"
RAW_TABLE = "agent_event_raw"
COVERAGE_TABLE = "trace_coverage"
SPOOL_SUFFIX = ".jsonl"


@dataclass
class WriteResult:
    written: int = 0
    duplicates: int = 0
    spooled: int = 0

    def add(self, other: WriteResult) -> None:
        self.written += other.written
        self.duplicates += other.duplicates
        self.spooled += other.spooled


def _jsonable(row: Mapping[str, Any]) -> dict[str, Any]:
    return {k: format_ts(v) if isinstance(v, datetime) else v for k, v in row.items()}


def event_from_json(row: Mapping[str, Any]) -> AgentEvent:
    data = dict(row)
    if isinstance(data.get("ts"), str):
        data["ts"] = parse_ts(data["ts"])
    return AgentEvent.model_validate(data)


def raw_from_json(row: Mapping[str, Any]) -> dict[str, Any]:
    data = dict(row)
    if isinstance(data.get("ts"), str):
        data["ts"] = parse_ts(data["ts"])
    return data


class Spool:
    """Append-only JSONL files in one directory. One file per writer process per day-ish."""

    def __init__(self, directory: Path) -> None:
        self.dir = Path(os.path.abspath(directory))
        self._lock = threading.Lock()
        self._name = f"spool-{os.getpid()}-{uuid.uuid4().hex[:8]}{SPOOL_SUFFIX}"

    def put(self, record: Mapping[str, Any]) -> Path:
        line = json.dumps(record, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        with self._lock:
            self.dir.mkdir(parents=True, exist_ok=True)
            path = self.dir / self._name
            with path.open("a", encoding="utf-8", newline="\n") as fh:
                fh.write(line + "\n")
                fh.flush()
                os.fsync(fh.fileno())
        return path

    def put_rows(self, events: Sequence[AgentEvent], raw: Sequence[Mapping[str, Any]]) -> Path:
        return self.put(
            {
                "kind": "rows",
                EVENT_TABLE: [_jsonable(e.row()) for e in events],
                RAW_TABLE: [_jsonable(r) for r in raw],
            }
        )

    def put_otlp(self, payload: Mapping[str, Any]) -> Path:
        return self.put({"kind": "otlp", "payload": payload})


class EventWriter:
    """Idempotent append of agent_event (+ agent_event_raw) rows; spool on store failure."""

    def __init__(self, tables: TableStore, spool: Spool | None = None) -> None:
        self.tables = tables
        self.spool = spool

    def _existing(self, table: str, ids: Iterable[str]) -> set[str]:
        key = "coverage_id" if table == COVERAGE_TABLE else "event_id"
        return {i for i in ids if self.tables.query(table, {key: i}, limit=1)}

    def _append_new(self, table: str, rows: Sequence[Any], key: Any) -> tuple[int, int]:
        """Append rows not yet stored. Returns (written, duplicates)."""
        unique: dict[str, Any] = {}
        for r in rows:
            unique.setdefault(key(r), r)
        dup = len(rows) - len(unique)
        if not unique:
            return 0, dup
        try:
            return self.tables.append(table, list(unique.values())), dup
        except DuplicateKeyError:
            pass  # some rows exist already (replay, second path): filter, then append the rest
        existing = self._existing(table, unique)
        fresh = [r for k, r in unique.items() if k not in existing]
        written = self.tables.append(table, fresh) if fresh else 0
        return written, dup + len(existing)

    def write_rows(
        self, events: Sequence[AgentEvent], raw: Sequence[Mapping[str, Any]] = ()
    ) -> WriteResult:
        if not events and not raw:
            return WriteResult()
        try:
            written, dup = self._append_new(EVENT_TABLE, events, lambda e: e.event_id)
            if raw:
                self._append_new(RAW_TABLE, raw, lambda r: r["event_id"])
            return WriteResult(written, dup, 0)
        except Exception:  # noqa: BLE001 - store down: keep the rows in the spool
            if self.spool is None:
                raise
        self.spool.put_rows(events, raw)
        return WriteResult(0, 0, len(events))

    def write(self, items: Sequence[Normalised]) -> WriteResult:
        return self.write_rows(
            [i.event for i in items], [i.raw for i in items if i.raw is not None]
        )

    def write_coverage(self, rows: Sequence[Mapping[str, Any]]) -> int:
        """Append trace_coverage rows not yet stored (idempotent by coverage_id)."""
        if not rows:
            return 0
        return self._append_new(COVERAGE_TABLE, rows, lambda r: r["coverage_id"])[0]

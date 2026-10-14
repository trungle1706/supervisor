"""Drain the recorder spool (and optional proxy logs) into ``agent_event``. Idempotent.

Run: python -m supervisor.jobs.ingest [--spool-dir DIR] [--proxy-log FILE ...]
Also callable in-process: ``run(settings, adapters)``.

Spool files (``*.jsonl`` in ``RECORDER_SPOOL_DIR``) are renamed to ``*.ingesting`` before
reading, so a writer that appends at the same time starts a new file. A file whose lines
are all handled becomes ``*.done``; lines that cannot be parsed go to ``*.rejected`` with
their line number, the error and the SHA-256 of the line (never the text: it may hold
PII). If the store fails, the file stays ``*.ingesting`` and the next run continues
with it; rows already stored count as duplicates (``event_id``), never twice.
"""

from __future__ import annotations

from supervisor.bootstrap import bootstrap

bootstrap()

import argparse  # noqa: E402
import hashlib  # noqa: E402
import json  # noqa: E402
import sys  # noqa: E402
from collections.abc import Sequence  # noqa: E402
from pathlib import Path  # noqa: E402
from typing import Any  # noqa: E402

from supervisor.adapters.factory import Adapters, build_adapters  # noqa: E402
from supervisor.config import Settings, load_settings  # noqa: E402
from supervisor.core.errors import SupervisorError  # noqa: E402
from supervisor.recorder.proxy_log import read_proxy_log  # noqa: E402
from supervisor.recorder.service import Recorder, build_recorder  # noqa: E402
from supervisor.recorder.sink import (  # noqa: E402
    EVENT_TABLE,
    RAW_TABLE,
    SPOOL_SUFFIX,
    event_from_json,
    raw_from_json,
)

INGESTING = ".ingesting"


def _counts() -> dict[str, int]:
    return {"files": 0, "lines": 0, "written": 0, "duplicates": 0, "rejected": 0, "ignored": 0}


def _handle_line(rec: Recorder, line: str, counts: dict[str, int]) -> None:
    """Store one spool line. Raises ValueError for a bad line; store errors propagate."""
    obj = json.loads(line)
    if not isinstance(obj, dict):
        raise ValueError("spool line must be a JSON object")
    kind = obj.get("kind")
    if kind == "rows":
        events = [event_from_json(r) for r in obj.get(EVENT_TABLE) or []]
        for e in events:
            if e.amount_minor is not None and not -(2**63) <= e.amount_minor < 2**63:
                raise ValueError("amount_minor outside the 64-bit range")
        raw = [raw_from_json(r) for r in obj.get(RAW_TABLE) or []]
        res = rec.writer.write_rows(events, raw)
        counts["written"] += res.written
        counts["duplicates"] += res.duplicates
    elif kind == "otlp":
        r = rec.ingest_otlp_json(obj.get("payload") or {}, "otlp")
        counts["written"] += r.written
        counts["duplicates"] += r.duplicates
        counts["ignored"] += r.ignored
    else:
        raise ValueError(f"unknown spool line kind {kind!r}")


def drain_file(rec: Recorder, path: Path, counts: dict[str, int]) -> None:
    work = path if path.suffix == INGESTING else path.with_name(path.stem + INGESTING)
    if work != path:
        path.replace(work)
    rejected: list[str] = []
    with work.open(encoding="utf-8") as fh:
        for n, line in enumerate(fh, start=1):
            if not line.strip():
                continue
            counts["lines"] += 1
            try:
                _handle_line(rec, line, counts)
            except (ValueError, OverflowError) as exc:  # bad line (pydantic/OTLP errors too)
                counts["rejected"] += 1
                msg = str(exc).splitlines()[0][:300]
                digest = hashlib.sha256(line.encode("utf-8")).hexdigest()
                rejected.append(json.dumps({"line": n, "error": msg, "line_sha256": digest}))
    if rejected:
        with work.with_name(work.stem + ".rejected").open("a", encoding="utf-8") as fh:
            fh.write("\n".join(rejected) + "\n")
    work.replace(work.with_name(work.stem + ".done"))
    counts["files"] += 1


def run(
    settings: Settings | None = None,
    adapters: Adapters | None = None,
    *,
    recorder: Recorder | None = None,
    spool_dir: Path | None = None,
    proxy_logs: Sequence[Path] = (),
) -> dict[str, int]:
    settings = settings or load_settings()
    adapters = adapters or build_adapters(settings)
    rec = recorder or build_recorder(settings, adapters.tables, use_spool=False)
    if rec.writer.spool is not None:
        rec = Recorder(rec.normaliser, type(rec.writer)(rec.writer.tables, None))
    counts = _counts()
    # WP10: a Volume spool with no local mount is staged to a local folder first.
    from supervisor.databricks.files import staged_spool

    with staged_spool(settings, spool_dir or settings.recorder_spool_dir) as directory:
        if directory is not None and Path(directory).is_dir():
            files = sorted(Path(directory).glob("*" + INGESTING)) + sorted(
                Path(directory).glob("*" + SPOOL_SUFFIX)
            )
            for path in files:
                drain_file(rec, path, counts)
    for log in proxy_logs:
        res = read_proxy_log(Path(log), rec.normaliser)
        w = rec.writer.write(res.items)
        rec.writer.write_coverage(res.coverage)
        counts["lines"] += len(res.items) + len(res.errors)
        counts["written"] += w.written
        counts["duplicates"] += w.duplicates
        counts["rejected"] += len(res.errors)
    return counts


def _ascii(text: str) -> str:
    return text.encode("ascii", "backslashreplace").decode("ascii")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="python -m supervisor.jobs.ingest")
    ap.add_argument("--spool-dir", type=Path, default=None, help="default: RECORDER_SPOOL_DIR")
    ap.add_argument("--proxy-log", type=Path, action="append", default=[], help="proxy JSONL")
    args = ap.parse_args(argv)
    try:
        settings = load_settings()
        for p in args.proxy_log:
            if not p.is_file():
                print(_ascii(f"[FAIL] proxy log not found: {p.resolve()}"))
                return 1
        counts: dict[str, Any] = run(
            settings,
            spool_dir=args.spool_dir.resolve() if args.spool_dir else None,
            proxy_logs=[p.resolve() for p in args.proxy_log],
        )
    except (SupervisorError, OSError) as exc:
        print(_ascii(f"[FAIL] ingest stopped: {exc}. Files left as *.ingesting; run again."))
        return 1
    except Exception as exc:  # noqa: BLE001 - store driver errors: message, not a traceback
        print(_ascii(f"[FAIL] ingest stopped ({type(exc).__name__}: {exc}). Run again."))
        return 1
    print(_ascii("[OK] ingest: " + ", ".join(f"{k}={v}" for k, v in counts.items())))
    return 0


if __name__ == "__main__":
    sys.exit(main())

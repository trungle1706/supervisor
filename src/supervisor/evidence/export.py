"""Export the evidence chain to a directory for offline verification.

Run: python -m supervisor.evidence.export <out dir> [--lane agent:<id>]... [--no-payloads]

Files (UTF-8, one canonical JSON object per line):

* ``entries.jsonl``     chain entries, grouped by lane, in seq order
* ``payloads.jsonl``    masked payloads (root payloads are always included)
* ``signatures.jsonl``  signatures of root entries (no key material)
* ``public_keys.jsonl`` public keys used by those signatures (+ ``public_key.pem``)
* ``anchors.jsonl``     anchor rows (receipts)
* ``manifest.json``     lane counts and heads, SHA-256 of every file

A lane export always includes the root lane, so signatures can be checked.
The output directory must not exist or must be empty.
"""

from __future__ import annotations

import argparse
import hashlib
import sys
from collections.abc import Iterable, Mapping, Sequence
from datetime import datetime
from pathlib import Path
from typing import Any

from supervisor.core.canonical import CANONICAL_VERSION, canonical_json, format_ts
from supervisor.core.errors import SupervisorError
from supervisor.core.ports import TableStore
from supervisor.evidence.verify import (
    CHAIN_SPEC_VERSION,
    EXPORT_FORMAT,
    ROOT_LANE,
)

ENTRY_COLS = (
    "lane",
    "seq",
    "ts",
    "record_type",
    "record_ref",
    "payload_hash",
    "prev_hash",
    "entry_hash",
    "writer",
    "env",
)
SIG_COLS = ("lane", "seq", "entry_hash", "signature", "key_id", "algorithm", "key_kind")


class ExportError(SupervisorError):
    """The export cannot be written."""


def _jsonable(row: Mapping[str, Any], cols: Sequence[str]) -> dict[str, Any]:
    out = {}
    for c in cols:
        v = row[c]
        out[c] = format_ts(v) if isinstance(v, datetime) else v
    return out


def _write_jsonl(path: Path, rows: Iterable[Mapping[str, Any]]) -> int:
    n = 0
    with path.open("w", encoding="utf-8", newline="\n") as fh:
        for row in rows:
            fh.write(canonical_json(row) + "\n")
            n += 1
    return n


def export_chain(
    tables: TableStore,
    out_dir: Path,
    *,
    lanes: Sequence[str] | None = None,
    include_payloads: bool = True,
    created_at: datetime | None = None,
) -> dict[str, Any]:
    """Write the export. Returns the manifest."""
    out_dir = Path(out_dir)
    if out_dir.exists() and any(out_dir.iterdir()):
        raise ExportError(f"export directory is not empty: {out_dir}")
    out_dir.mkdir(parents=True, exist_ok=True)

    if lanes:
        wanted = sorted(set(lanes) | {ROOT_LANE})
        entries = [
            r for lane in wanted for r in tables.query("chain_entry", {"lane": lane}, ["seq"])
        ]
        payloads = [
            r for lane in wanted for r in tables.query("chain_payload", {"lane": lane}, ["seq"])
        ]
    else:
        entries = tables.query("chain_entry", order_by=["lane", "seq"])
        payloads = tables.query("chain_payload", order_by=["lane", "seq"])
    entries.sort(key=lambda r: (r["lane"] != ROOT_LANE, r["lane"], r["seq"]))
    if not include_payloads:
        payloads = [p for p in payloads if p["lane"] == ROOT_LANE]
    payloads.sort(key=lambda r: (r["lane"] != ROOT_LANE, r["lane"], r["seq"]))
    sigs = tables.query("chain_signature", {"lane": ROOT_LANE}, ["seq"])
    anchors = tables.query("anchor", order_by=["seq_to"])

    keys: dict[str, dict[str, str]] = {}
    for s in sigs:
        keys.setdefault(
            s["key_id"],
            {
                "key_id": s["key_id"],
                "algorithm": s["algorithm"],
                "key_kind": s["key_kind"],
                "public_key": s["public_key"],
            },
        )
    counts = {
        "entries.jsonl": _write_jsonl(
            out_dir / "entries.jsonl", (_jsonable(r, ENTRY_COLS) for r in entries)
        ),
        "payloads.jsonl": _write_jsonl(
            out_dir / "payloads.jsonl",
            (_jsonable(r, ("lane", "seq", "payload_hash", "payload")) for r in payloads),
        ),
        "signatures.jsonl": _write_jsonl(
            out_dir / "signatures.jsonl", (_jsonable(r, SIG_COLS) for r in sigs)
        ),
        "public_keys.jsonl": _write_jsonl(
            out_dir / "public_keys.jsonl", (keys[k] for k in sorted(keys))
        ),
        "anchors.jsonl": _write_jsonl(
            out_dir / "anchors.jsonl",
            (_jsonable(r, tuple(r.keys())) for r in anchors),
        ),
    }
    if sigs:
        (out_dir / "public_key.pem").write_text(sigs[-1]["public_key"], encoding="ascii")
        counts["public_key.pem"] = 1

    lane_info: dict[str, dict[str, Any]] = {}
    for r in entries:
        info = lane_info.setdefault(r["lane"], {"count": 0, "seq_from": r["seq"]})
        info["count"] += 1
        info["seq_to"] = r["seq"]
        info["head"] = r["entry_hash"]
    files = {
        name: {
            "sha256": hashlib.sha256((out_dir / name).read_bytes()).hexdigest(),
            "lines": n,
        }
        for name, n in sorted(counts.items())
    }
    manifest = {
        "format": EXPORT_FORMAT,
        "chain_spec_version": CHAIN_SPEC_VERSION,
        "canonical_version": CANONICAL_VERSION,
        "created_at": format_ts(created_at) if created_at else None,
        "scope": "lanes" if lanes else "all",
        "lanes": lane_info,
        "payloads_included": include_payloads,
        "key_ids": sorted(keys),
        "files": files,
    }
    (out_dir / "manifest.json").write_text(
        canonical_json(manifest) + "\n", encoding="utf-8", newline="\n"
    )
    return manifest


def main(argv: list[str] | None = None) -> int:
    from supervisor.bootstrap import bootstrap

    bootstrap()
    from supervisor.adapters.factory import build_adapters
    from supervisor.config import load_settings

    ap = argparse.ArgumentParser(prog="python -m supervisor.evidence.export")
    ap.add_argument("out_dir")
    ap.add_argument("--lane", action="append", default=None, help="agent:<id> (repeatable)")
    ap.add_argument("--no-payloads", action="store_true", help="omit agent-lane payloads")
    args = ap.parse_args(argv)
    try:
        settings = load_settings()
        adapters = build_adapters(settings)
        manifest = export_chain(
            adapters.tables,
            Path(args.out_dir),
            lanes=args.lane,
            include_payloads=not args.no_payloads,
            created_at=adapters.clock.now(),
        )
    except SupervisorError as exc:
        print(f"[FAIL] {exc}".encode("ascii", "backslashreplace").decode("ascii"))  # noqa: T201
        return 1
    total = sum(v["count"] for v in manifest["lanes"].values())
    line = f"[OK] exported {total} entries in {len(manifest['lanes'])} lane(s) to {args.out_dir}"
    print(line.encode("ascii", "backslashreplace").decode("ascii"))  # noqa: T201
    return 0


if __name__ == "__main__":
    sys.exit(main())

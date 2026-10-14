"""Anchor job: write the latest signed root entry (+ public key) to the anchor target.

Run: python -m supervisor.jobs.anchor [--seal]
Also callable in-process (scheduler): ``run(settings, adapters, writer=app_writer, seal=True)``.

Idempotent: a root that already has an ``anchor`` row is skipped. If an earlier run
wrote the file but crashed before the row, the document is rebuilt byte-identical,
the receipt is recomputed and the row is written.

``--seal`` first writes a new signed root entry. Use it only when no other chain
writer runs (single-writer rule); the app's scheduler passes its own writer instead.
"""

from __future__ import annotations

from supervisor.bootstrap import bootstrap

bootstrap()

import argparse  # noqa: E402
import sys  # noqa: E402
from typing import Any  # noqa: E402

from supervisor.adapters.factory import Adapters, build_adapters  # noqa: E402
from supervisor.config import Settings, load_settings  # noqa: E402
from supervisor.core.errors import SupervisorError  # noqa: E402
from supervisor.core.models import Anchor as AnchorRow  # noqa: E402
from supervisor.evidence.anchor import (  # noqa: E402
    AnchorError,
    anchor_document,
    build_anchor,
    receipt_for,
)
from supervisor.evidence.chain import ChainWriter, build_chain_writer  # noqa: E402
from supervisor.evidence.verify import ROOT_LANE, ROOT_RECORD_TYPE  # noqa: E402

ENTRY_FIELDS = (
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


def run(
    settings: Settings | None = None,
    adapters: Adapters | None = None,
    *,
    anchor: Any = None,
    writer: ChainWriter | None = None,
    seal: bool = False,
) -> dict[str, Any]:
    """Anchor the latest signed root. Returns a small status dict."""
    settings = settings or load_settings()
    adapters = adapters or build_adapters(settings)
    anchor = anchor or build_anchor(settings)
    tables = adapters.tables
    if seal:
        own = writer is None
        writer = writer or build_chain_writer(settings, tables, adapters.clock)
        try:
            writer.commit_root(force=False)
        finally:
            if own:
                writer.close(seal=False)
    roots = tables.query(
        "chain_entry",
        {"lane": ROOT_LANE, "record_type": ROOT_RECORD_TYPE},
        order_by=["-seq"],
        limit=1,
    )
    if not roots:
        return {"status": "skipped", "reason": "no signed root entry yet"}
    root = roots[0]
    done = tables.query("anchor", {"root_hash": root["entry_hash"]}, limit=1)
    if done:
        return {"status": "skipped", "reason": "latest root already anchored", "seq": root["seq"]}
    sigs = tables.query("chain_signature", {"lane": ROOT_LANE, "seq": root["seq"]}, limit=1)
    payloads = tables.query("chain_payload", {"lane": ROOT_LANE, "seq": root["seq"]}, limit=1)
    if not sigs or not payloads:
        raise AnchorError(f"root seq {root['seq']} has no signature or payload row")
    sig = sigs[0]
    entry = {k: root[k] for k in ENTRY_FIELDS}
    name, data = anchor_document(entry, payloads[0]["payload"], sig, sig["public_key"])
    exists = getattr(anchor, "exists", None)
    if callable(exists) and exists(name):
        receipt = receipt_for(data, anchor.location(name))  # recovered after a crash
    else:
        receipt = anchor.put(name, data)
    prev = tables.query("anchor", {"lane": ROOT_LANE}, order_by=["-seq_to"], limit=1)
    seq_from = prev[0]["seq_to"] + 1 if prev else 0
    row = AnchorRow(
        anchor_id=f"anchor:{root['entry_hash'][:32]}",
        lane=ROOT_LANE,
        seq_from=seq_from,
        seq_to=root["seq"],
        root_hash=root["entry_hash"],
        head_signature=sig["signature"],
        key_id=sig["key_id"],
        anchored_at=adapters.clock.now(),
        anchor_target=anchor.target,
        receipt=receipt,
    )
    tables.append("anchor", [row])
    return {"status": "anchored", "seq": root["seq"], "name": name, "receipt": receipt}


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="python -m supervisor.jobs.anchor")
    ap.add_argument(
        "--seal",
        action="store_true",
        help="write a new signed root first (only when no other chain writer runs)",
    )
    args = ap.parse_args(argv)
    try:
        result = run(seal=args.seal)
    except SupervisorError as exc:
        print(f"[FAIL] {exc}".encode("ascii", "backslashreplace").decode("ascii"))
        return 1
    if result["status"] == "anchored":
        line = f"[OK] anchored root seq {result['seq']}: {result['receipt']}"
    else:
        line = f"[SKIP] {result['reason']}"
    print(line.encode("ascii", "backslashreplace").decode("ascii"))
    return 0


if __name__ == "__main__":
    sys.exit(main())

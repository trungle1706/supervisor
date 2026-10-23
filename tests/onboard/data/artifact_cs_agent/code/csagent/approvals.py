"""Approval store: the record a person leaves when they approve a fee waiver.

The agent app writes it (POST /approve/{thread_id}); the Supervisor policy reads the same record
through a fact source (`fact.approval.approved`, key = tool argument `approval_id`). Locally it is
a JSON file (APPROVALS_FILE). On a Databricks App this is a Delta table of the bank's approval
system; this file store is the stand-in (see README, limits).
"""
from __future__ import annotations

import json
import os
import threading
import time
import uuid
from pathlib import Path
from typing import Any

_LOCK = threading.Lock()


def _path() -> Path:
    return Path(os.environ.get("APPROVALS_FILE", "approvals.json")).resolve()


def _load() -> dict[str, Any]:
    p = _path()
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def _save(data: dict[str, Any]) -> None:
    p = _path()
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=1, sort_keys=True), encoding="utf-8")
    os.replace(tmp, p)


def request(thread_id: str, call: dict[str, Any], requested_by: str) -> str:
    """Open a pending approval for one waive_fee call. Returns the approval id."""
    aid = "APR-" + uuid.uuid4().hex[:10].upper()
    args = call.get("args") or {}
    rec = {"approval_id": aid, "thread_id": thread_id, "tool": call.get("name"),
           "fee_id": args.get("fee_id"), "account_id": args.get("account_id"),
           "amount_minor": args.get("amount_minor"), "status": "pending", "approved": False,
           "requested_by": requested_by, "approver": None, "note": "", "used": False,
           "created_at": int(time.time()), "decided_at": None}
    with _LOCK:
        data = _load()
        data[aid] = rec
        _save(data)
    return aid


def decide(approval_id: str, approver: str, approve: bool, note: str = "") -> dict[str, Any]:
    with _LOCK:
        data = _load()
        rec = data.get(approval_id)
        if rec is None:
            raise KeyError(approval_id)
        if rec["status"] != "pending":
            raise ValueError(f"approval {approval_id} is already {rec['status']}")
        if approver == rec["requested_by"]:
            raise PermissionError("segregation of duties: the requester cannot approve")
        rec.update(status="approved" if approve else "rejected", approved=bool(approve),
                   approver=approver, note=note[:300], decided_at=int(time.time()))
        _save(data)
        return dict(rec)


def get(approval_id: str) -> dict[str, Any] | None:
    with _LOCK:
        rec = _load().get(approval_id)
        return dict(rec) if rec else None


def consume(approval_id: str, fee_id: str, account_id: str, amount_minor: int) -> None:
    """Check in code that the approval covers exactly this waiver, then mark it used."""
    with _LOCK:
        data = _load()
        rec = data.get(approval_id)
        if not rec or not rec.get("approved"):
            raise PermissionError("no approved approval record for this waiver")
        if rec.get("used"):
            raise PermissionError("approval already used")
        if (rec["fee_id"], rec["account_id"], rec["amount_minor"]) != (fee_id, account_id, amount_minor):
            raise PermissionError("approval does not match this waiver")
        rec["used"] = True
        _save(data)

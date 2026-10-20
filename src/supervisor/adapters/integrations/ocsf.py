"""OCSF 1.x output for the SIEM export (WP21, ADR D15). Pure functions, no I/O.

A SiemEvent (ids, hashes and enums only; see ``siem.py``) is mapped to the closest OCSF
class. We emit the OCSF *base event* required attributes plus the class attributes we have
data for; anything else Supervisor-specific goes in ``unmapped``. This is a documented
subset, not a full conformance claim (``docs/siem.md``). Free text and personal data are
never part of the event, so they are never part of the OCSF document.

====================  =====  ========  ==============================================
Supervisor event      class  category  why
====================  =====  ========  ==============================================
gate_decision         6003   6         API Activity: a tool call checked by the gate
gate_state_change     6003   6         API Activity: a control-plane call (pause, ...)
chain_root/anchor     6003   6         API Activity: evidence sealing call
case_opened/event     2004   2         Detection Finding: an incident case
alert                 2004   2         Detection Finding: a fired alert rule
chain_anomaly         2004   2         Detection Finding: chain verify failure
ingress_reject        3002   3         Authentication: ingress credential refused
====================  =====  ========  ==============================================
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from supervisor.core.canonical import canonical_json

OCSF_VERSION = "1.1.0"

# class_uid -> (category_uid, class_name, category_name)
CLASSES: dict[int, tuple[int, str, str]] = {
    6003: (6, "API Activity", "Application Activity"),
    2004: (2, "Detection Finding", "Findings"),
    3002: (3, "Authentication", "Identity & Access Management"),
}

EVENT_CLASS: dict[str, int] = {
    "gate_decision": 6003,
    "gate_state_change": 6003,
    "chain_root": 6003,
    "chain_anchor": 6003,
    "case_opened": 2004,
    "case_event": 2004,
    "alert": 2004,
    "chain_anomaly": 2004,
    "ingress_reject": 3002,
}

# OCSF activity_id per (class, event_type). 99 = Other; the exact word is in activity_name.
_ACTIVITY: dict[str, int] = {
    "case_opened": 1,  # Detection Finding: Create
    "alert": 1,
    "chain_anomaly": 1,
    "case_event": 2,  # Detection Finding: Update
    "ingress_reject": 1,  # Authentication: Logon
}
_API_OTHER = 99

# disposition_id (OCSF 1.1): 1 Allowed, 2 Blocked, 3 Quarantined, 15 Detected
_DISPOSITION = {
    "allow": 1,
    "log": 1,
    "alert": 15,
    "block": 2,
    "pause": 2,
    "quarantine": 3,
}

_SEV_NAMES = {0: "Unknown", 1: "Informational", 2: "Low", 3: "Medium", 4: "High", 5: "Critical"}


def severity_id(cef: int) -> int:
    """CEF 0..10 -> OCSF severity_id 0..5 (6 Fatal is never used)."""
    if cef <= 0:
        return 0
    if cef <= 2:
        return 1
    if cef <= 4:
        return 2
    if cef <= 6:
        return 3
    if cef <= 8:
        return 4
    return 5


def _time_ms(ts: str) -> int:
    dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
    return int(dt.timestamp() * 1000)


def to_ocsf_dict(event: Any) -> dict[str, Any]:
    """One OCSF event (a plain dict). ``event`` is a ``siem.SiemEvent``."""
    class_uid = EVENT_CLASS.get(event.event_type, 6003)
    category_uid, class_name, category_name = CLASSES[class_uid]
    activity_id = _ACTIVITY.get(event.event_type, _API_OTHER)
    type_uid = class_uid * 100 + activity_id
    sev = severity_id(event.severity)
    doc: dict[str, Any] = {
        "activity_id": activity_id,
        "activity_name": f"{event.event_type}:{event.outcome}",
        "category_uid": category_uid,
        "category_name": category_name,
        "class_uid": class_uid,
        "class_name": class_name,
        "severity_id": sev,
        "severity": _SEV_NAMES[sev],
        "time": _time_ms(event.ts),
        "type_uid": type_uid,
        "metadata": {
            "version": OCSF_VERSION,
            "uid": event.event_id,
            "product": {
                "name": event.product,
                "vendor_name": event.vendor,
                "version": event.version,
            },
            "log_name": event.schema,
        },
    }
    if class_uid == 6003:
        outcome = event.outcome
        doc["api"] = {"operation": f"{event.event_type}:{outcome}"}
        doc["actor"] = {"user": {"uid": event.actor or "supervisor-system"}}
        doc["status_id"] = 2 if outcome in ("block", "pause", "quarantine") else 1
        if outcome in _DISPOSITION:
            doc["disposition_id"] = _DISPOSITION[outcome]
            doc["action_id"] = 2 if _DISPOSITION[outcome] in (2, 3) else 1
    elif class_uid == 2004:
        doc["finding_info"] = {
            "uid": event.case_id or event.event_id,
            "title": f"{event.event_type}:{event.rule_id or event.outcome}",
            "types": [event.event_type],
        }
        doc["status_id"] = 1
    else:  # 3002 Authentication: an ingress rejection
        doc["status_id"] = 2
        doc["user"] = {"uid": event.agent_id or "unknown"}
    if event.agent_id:
        doc["resources"] = [{"type": "AI Agent", "uid": event.agent_id}]
    unmapped: dict[str, Any] = {
        "event_id": event.event_id,
        "event_type": event.event_type,
        "outcome": event.outcome,
        "rule_id": event.rule_id,
        "case_id": event.case_id,
        "chain_lane": event.chain_lane,
        "chain_seq": event.chain_seq,
        "entry_hash": event.entry_hash,
        "env": event.env,
    }
    attrs = getattr(event, "attrs", None)
    if attrs:
        unmapped["attrs"] = dict(attrs)
    doc["unmapped"] = {k: v for k, v in unmapped.items() if v not in (None, "")}
    return doc


def to_ocsf_json(event: Any) -> str:
    """Canonical JSON (sorted keys), one line."""
    return canonical_json(to_ocsf_dict(event))


__all__ = [
    "CLASSES",
    "EVENT_CLASS",
    "OCSF_VERSION",
    "severity_id",
    "to_ocsf_dict",
    "to_ocsf_json",
]

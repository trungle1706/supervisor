"""Re-open the duties of a system after a law change (WP-W2, governance event ``regkb_changed``).

The governance rule runner calls ``reopen`` for one system and one applied change
(``regkb_change``). All of it is deterministic; no model is called.

* Every ``obligation_status`` row of the system that maps to an affected obligation gets the note
  "article changed on <date> (package <sha8>)". A row that is closed or waived (and applies) goes
  back to ``open`` with the closing control cleared; a row that is open stays open.
* For each re-opened row group (instrument and coverage) one task is made with the title of the
  WP-L3 gap task ("Close N duties of <number> (coverage partial)"; a group with full or unknown
  coverage is a "Re-check ..." task). The template id holds the package sha, so a repeat is a
  no-op.
* One chain record ``regkb_reopen`` per system and change, integers and ids only.

Advisory only. Not legal advice. Bank counsel must confirm.
"""

from __future__ import annotations

import datetime as dt
import json
import logging
from collections.abc import Iterable
from typing import Any

from supervisor.core.errors import ConcurrencyError
from supervisor.governance import duties_gap
from supervisor.governance.register_v2 import duties as dut

log = logging.getLogger("supervisor.governance.actions")

TEMPLATE_PREFIX = "DUTY-CHG-"
MAX_IDS_IN_TASK = dut.MAX_IDS_IN_TASK


def json_list(value: Any) -> list[Any]:
    if isinstance(value, list):
        return value
    try:
        out = json.loads(value) if value else []
    except (TypeError, ValueError):
        return []
    return out if isinstance(out, list) else []


def note_text(applied_at: Any, package_sha: str) -> str:
    day = applied_at.date().isoformat() if hasattr(applied_at, "date") else str(applied_at)[:10]
    return f"article changed on {day} (package {package_sha[:8]})"


def _instrument_name(settings: Any, instrument_id: str) -> str:
    try:
        return str(duties_gap.kb_of(settings).instrument(instrument_id).number or instrument_id)
    except Exception:  # noqa: BLE001 - a name is only for the title
        return instrument_id


def _task_title(n: int, name: str, cov: str) -> str:
    noun = "duty" if n == 1 else "duties"
    if cov in ("partial", "none"):
        return f"Close {n} {noun} of {name} (coverage {cov})"
    return f"Re-check {n} {noun} of {name} after a law change (coverage {cov})"


def reopen(
    ctx: Any, settings: Any, system_id: str, change_id: str, actor: str
) -> tuple[str, dict[str, int]]:
    """Returns (status, counts). status is ``done`` or ``skipped`` (no change, no system, no
    row for the affected obligations)."""

    change = ctx.state.get("regkb_change", {"change_id": change_id})
    system = ctx.state.get("ai_system", {"system_id": system_id})
    counts = {"rows_n": 0, "reopened_n": 0, "tasks_n": 0}
    if change is None or system is None or change["status"] != "applied":
        return "skipped", counts
    ids = [str(x) for x in json_list(change["obligations_affected"])]
    note = note_text(change["applied_at"], str(change["package_sha"]))
    flipped: list[dict[str, Any]] = []
    for oid in sorted(set(ids)):
        row = ctx.state.get("obligation_status", {"status_id": dut.status_id(system_id, oid)})
        if row is None:
            continue
        counts["rows_n"] += 1
        reopen_it = row["applies"] == "yes" and row["status"] != duties_gap.OPEN_STATE
        changes: dict[str, Any] = {"note": duties_gap._note(note, row["note"])}  # noqa: SLF001
        if reopen_it:
            changes.update(status=duties_gap.OPEN_STATE, closing_control=None)
        try:
            ctx.state.update(
                "obligation_status",
                {"status_id": row["status_id"]},
                changes,
                int(row["row_version"]),
            )
        except ConcurrencyError:
            log.warning("regkb_changed: duty row %s changed meanwhile; left as it is", oid)
            continue
        if reopen_it:
            counts["reopened_n"] += 1
            flipped.append({**dict(row), **changes})
    counts["tasks_n"] = _tasks(ctx, settings, system, str(change["package_sha"]), flipped, actor)
    if counts["rows_n"]:
        try:
            ctx.evidence.record(
                "regkb_reopen",
                f"system:{system_id}",
                {
                    "system_id": system_id,
                    "change_id": change_id,
                    "package_sha256": str(change["package_sha"]),
                    "instrument_id": str(change["instrument_id"]),
                    **counts,
                },
            )
        except Exception:  # noqa: BLE001 - the rows are written; the log has the cause
            log.exception("regkb_reopen chain record failed")
    return ("done" if counts["rows_n"] else "skipped"), counts


def _tasks(
    ctx: Any,
    settings: Any,
    system: Any,
    package_sha: str,
    rows: Iterable[dict[str, Any]],
    actor: str,
) -> int:
    from supervisor.tasks.service import TaskService

    groups: dict[tuple[str, str], list[str]] = {}
    for r in rows:
        groups.setdefault((str(r["instrument_id"]), str(r["coverage"])), []).append(
            str(r["obligation_id"])
        )
    if not groups:
        return 0
    tasks = TaskService(ctx.state, ctx.tables, ctx.clock, settings, evidence=ctx.evidence)
    made = 0
    sid = str(system["system_id"])
    for (instrument_id, cov), oids in sorted(groups.items()):
        oids.sort()
        shown = ", ".join(oids[:MAX_IDS_IN_TASK])
        if len(oids) > MAX_IDS_IN_TASK:
            shown += f", ... and {len(oids) - MAX_IDS_IN_TASK} more"
        trow = tasks._row_for(  # noqa: SLF001 - the one place that writes a task for a system
            sid,
            str(system["lifecycle_stage"]),
            template_id=f"{TEMPLATE_PREFIX}{package_sha[:8]}-{instrument_id}-{cov}",
            kind="custom",
            title=_task_title(len(oids), _instrument_name(settings, instrument_id), cov),
            owner_role="owner",
            required=False,
            due_days=duties_gap.DEFAULT_DUE_DAYS,
            evidence_kind="none",
            evidence_ref=f"{duties_gap.BANNER} {shown}",
            level="low",
            d33_class="unclassified",
            actor=actor,
        )
        trow["due_at"] = ctx.clock.now() + dt.timedelta(days=duties_gap.DEFAULT_DUE_DAYS)
        if tasks._insert(trow, actor):  # noqa: SLF001
            made += 1
    return made

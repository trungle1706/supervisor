"""Effectiveness evidence for the duties of an AI system (WP-L4, flag ``REGULATOR_PACK``).

A duty (RegKB obligation) maps to Supervisor controls in its ``control_mapping`` (kinds
catalogue, rule, monitor, evidence, console; kind ``process`` is a bank process and never a
Supervisor control). For one system this module reads, per mapped control id, how many evidence
rows exist in a window (default 30 days, integers only) for the supervised agents of the system:

=============  =================================================================================
counter        rows counted in the window
=============  =================================================================================
rule           tier-0 verdict hits that the gate enforced (``risk.evidence.Collector.rule_hits``)
gate           gate decisions (``agent_event``, ``event_type = gate_decision``)
findings       detector findings that ran (``finding``, no ``not_executed_reason``)
verdicts       non-mock verdict rows (``verdict_log``)
judge          non-mock tier 1 and tier 2 verdicts. ADVISORY: a judge never changes a control
               decision (rule R1), so they are shown but never make a control "work"
chain          entries on the agent lanes of the chain; chain verifications and audit packs on
               the root lane
packs          non-mock assurance results on the agent or its traces (``eval_result``)
monitor        daily ``oversight_metric`` rows; for drift, fairness and multiagent only rows whose
               monitor status is ``ok`` (the ``risk.evidence`` rule)
others         cases, sign-offs, coverage, versions, baselines, fairness slices, anchors, events
=============  =================================================================================

A control **works** when it has at least ``DUTY_EVIDENCE_MIN_ROWS`` (default 1) rows and is not
advisory. A control with no counter here (a console screen, an onboarding artefact, the quality
and sweeps monitors) is *unmeasured*: it has no rows, so it never works. A system with no
supervised agent (gate state RUNNING, PAUSED or QUARANTINED) has no evidence at all.

Hub rules of WP-L4:

* (a) ``refresh`` closes an open applying row with coverage ``full`` by itself when it has mapped
  Supervisor controls and all of them work: status closed, ``closing_control`` = the control ids
  joined by ",", note = banner + "closed by evidence <window> <counts>". Rows with coverage
  partial or none are never closed here.
* (b) ``close_group_tasks``: when the last open row of a WP-L2 gap group (instrument x coverage)
  is closed, the task ``DUTY-<instrument id>-<coverage>`` is closed through the task service.
* (c) ``split_note`` reads the typed close evidence or waive reason from ``note`` after the
  banner; the control comes from ``closing_control``.

Advisory only. Not legal advice. Bank counsel must confirm.
"""

from __future__ import annotations

import logging
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from typing import Any

from supervisor.core.canonical import format_ts
from supervisor.governance import duties_gap as dg
from supervisor.risk import evidence as ev

log = logging.getLogger("supervisor.governance")

BANNER = dg.BANNER
ACTOR = "system"
TASK_ACTOR = "system:duty_evidence"
SCAN_CAP = ev.SCAN_CAP
SYSTEM_PROCESS = "process"
MAX_CONTROLS = 40

# kind catalogue: capability id -> counter
CATALOGUE: dict[str, str] = {
    "amount_valid": "gate",
    "approved_tools": "gate",
    "daily_aggregate": "gate",
    "pii_bulk_read": "gate",
    "pii_masking": "gate",
    "prior_read": "gate",
    "single_limit": "gate",
    "split_payment": "gate",
    "system_of_record": "gate",
    "injection_prefilter": "findings",
    "evidence_chain": "chain_lane",
    "case_files": "cases",
    "drift_band": "mon:drift",
    "fairness_slices": "mon:fairness",
    "groundedness": "judge",
    "tier1_monitor": "judge",
    "tier2_judge": "judge",
    "otlp_ingest": "otlp",
    "proxy_log": "proxy",
}
# kind evidence: evidence artefact id -> counter
EVIDENCE: dict[str, str] = {
    "agent_event_log": "events",
    "agent_registry": "agents",
    "agent_version": "versions",
    "anchor": "anchor",
    "audit_pack": "audit_pack",
    "case_file": "cases",
    "chain_verify_report": "chain_verify",
    "coverage_rows": "coverage",
    "evidence_chain": "chain_lane",
    "fairness_slice": "fairness_rows",
    "launch_report": "packs",
    "oversight_metric": "mon:oversight",
    "policy_baseline": "baseline",
    "signoff_record": "signoff",
    "verdict_log": "verdicts",
}
# kind monitor: module name -> counter (quality and sweeps are not evidence: rule R1, no status)
MONITOR: dict[str, str] = {
    "drift": "mon:drift",
    "fairness": "mon:fairness",
    "multiagent": "mon:multiagent",
    "oversight": "mon:oversight",
}
# where a counter reads, for the pointers of the pack
SOURCE_OF: dict[str, str] = {
    "rule": "verdict (tier 0 rule hits)",
    "gate": "agent_event (gate_decision)",
    "findings": "finding",
    "verdicts": "verdict",
    "judge": "verdict (tier 1 and 2, advisory)",
    "chain_lane": "chain_entry (agent lanes)",
    "chain_verify": "chain_entry (chain_verify)",
    "audit_pack": "chain_entry (audit_pack_built)",
    "packs": "eval_result",
    "cases": "cases",
    "signoff": "signoff",
    "coverage": "coverage",
    "versions": "agent_version",
    "baseline": "policy_baseline",
    "fairness_rows": "fairness_slice",
    "anchor": "anchor",
    "events": "agent_event",
    "otlp": "agent_event (not proxy)",
    "proxy": "agent_event (proxy)",
    "agents": "agent",
    "mon:drift": "oversight_metric (drift ok)",
    "mon:fairness": "oversight_metric (fairness ok)",
    "mon:multiagent": "oversight_metric (multiagent ok)",
    "mon:oversight": "oversight_metric",
    "unmeasured": "no counter",
}
ADVISORY = frozenset({"judge"})


# ------------------------------------------------------------------------------ switches


def enabled(settings: Any) -> bool:
    """REGULATOR_PACK is on and what it needs is on (GOVERNANCE_ENABLED, RISK_DUTIES, and so
    CONSOLE_SYSTEMS_ENABLED)."""
    return bool(getattr(settings, "regulator_pack", False) and dg.enabled(settings))


def ensure_on(settings: Any) -> None:
    if not enabled(settings):
        raise dg.DutyError(
            "regulator_pack_off",
            "the regulator pack and duty evidence are off (REGULATOR_PACK=1 turns them on; it "
            "needs GOVERNANCE_ENABLED and RISK_DUTIES)",
        )


def sweep_enabled(settings: Any) -> bool:
    return bool(enabled(settings) and int(getattr(settings, "duty_evidence_sweep_s", 0)) >= 300)


@dataclass
class Env:
    """The parts of a context this module needs, so the console and the scheduler job share it."""

    state: Any
    tables: Any
    clock: Any
    settings: Any
    tasks: Any
    sink: Any

    @classmethod
    def from_console(cls, ctx: Any) -> Env:
        return cls(ctx.state, ctx.tables, ctx.clock, ctx.settings, ctx.tasks, ctx.runtime.chain)

    @classmethod
    def from_job(cls, mctx: Any, settings: Any) -> Env:
        from supervisor.tasks.service import TaskService

        tasks = TaskService(mctx.state, mctx.tables, mctx.clock, settings, evidence=mctx.evidence)
        return cls(mctx.state, mctx.tables, mctx.clock, settings, tasks, mctx.evidence)

    def window(self) -> ev.Window:
        return ev.window_for(self.clock.now(), int(self.settings.duty_evidence_window_days))


# ------------------------------------------------------------------------------ the mapping


def mapped_controls(obligation: Any) -> list[tuple[str, str, str]]:
    """``(kind, id, coverage)`` of the Supervisor controls of a duty: every ``control_mapping``
    entry that is not a bank process and has coverage other than ``none``. Each id once."""
    out: dict[str, tuple[str, str, str]] = {}
    for c in getattr(obligation, "control_mapping", ()) or ():
        if c.kind == SYSTEM_PROCESS or c.coverage == "none":
            continue
        out.setdefault(str(c.id), (str(c.kind), str(c.id), str(c.coverage)))
    return sorted(out.values(), key=lambda x: x[1])[:MAX_CONTROLS]


def counter_of(kind: str, cid: str) -> str:
    """The counter that reads the rows of a mapped control; ``unmeasured`` when none does."""
    if kind == "rule":
        return "rule"
    table = {"catalogue": CATALOGUE, "evidence": EVIDENCE, "monitor": MONITOR}.get(kind)
    return (table or {}).get(cid, "unmeasured")


# ------------------------------------------------------------------------------ the reader


def _true(value: Any) -> bool:
    return ev._true(value)  # noqa: SLF001 - the one definition of a stored boolean


class Reader:
    """Reads the integer counts of one system in one window. One reader asks each (counter,
    argument) question once."""

    def __init__(
        self, env: Env, agents: list[str], w: ev.Window, collector: ev.Collector | None
    ) -> None:
        self.env = env
        self.agents = agents
        self.w = w
        self.col = collector
        self._memo: dict[tuple[str, str], int] = {}

    def _in(self, value: Any) -> bool:
        ts = ev._ts(value)  # noqa: SLF001
        return ts is not None and self.w.start <= ts < self.w.end

    def _each(
        self,
        store: Any,
        table: str,
        ts_col: str | None,
        where: Mapping[str, Any] | None = None,
        pred: Any = None,
        by: str = "agent_id",
    ) -> int:
        n = 0
        for a in self.agents:
            rows = store.query(
                table,
                {by: a, **(where or {})},
                order_by=(f"-{ts_col}",) if ts_col else (),
                limit=SCAN_CAP,
            )
            for r in rows:
                if ts_col and not self._in(r[ts_col]):
                    continue
                if pred is not None and not pred(r):
                    continue
                n += 1
        return n

    def _root(self, record_type: str) -> int:
        rows = self.env.tables.query(
            "chain_entry",
            {"lane": "root", "record_type": record_type},
            order_by=("-seq",),
            limit=SCAN_CAP,
        )
        return sum(1 for r in rows if self._in(r["ts"]))

    def _case_ids(self) -> list[str]:
        out: list[str] = []
        for a in self.agents:
            out += [str(c["case_id"]) for c in self.env.state.query("cases", {"agent_id": a})]
        return out

    def _monitor(self, name: str | None) -> int:
        """Days (rows) of ``oversight_metric`` in the window; with a monitor name only the rows
        whose status for that monitor is ``ok``."""
        n = 0
        for a in self.agents:
            for r in self.env.state.query("oversight_metric", {"agent_id": a}):
                day = ev._date(r.get("metric_date"))  # noqa: SLF001
                if day is None or not (self.w.start.date() <= day < self.w.end.date()):
                    continue
                if name is None:
                    n += 1
                    continue
                status = (ev._json(r.get("monitor_status")) or {}).get(name) or {}  # noqa: SLF001
                if isinstance(status, Mapping) and status.get("status") == "ok":
                    n += 1
        return n

    def count(self, counter: str, arg: str = "") -> int:
        """Integer rows for one counter. ``arg`` is the rule id for counter ``rule``."""
        if not self.agents:
            return 0
        key = (counter, arg)
        if key not in self._memo:
            self._memo[key] = max(0, int(self._read(counter, arg)))
        return self._memo[key]

    def _read(self, counter: str, arg: str) -> int:
        t, s = self.env.tables, self.env.state
        if counter == "rule":
            if self.col is None:
                return 0
            return int(self.col.rule_hits(self.agents, arg, self.w)[0])
        if counter == "gate":
            return self._each(t, "agent_event", "ts", {"event_type": "gate_decision"})
        if counter == "events":
            return self._each(t, "agent_event", "ts")
        if counter == "otlp":
            return self._each(t, "agent_event", "ts", pred=lambda r: r.get("source") != "proxy")
        if counter == "proxy":
            return self._each(t, "agent_event", "ts", pred=lambda r: r.get("source") == "proxy")
        if counter == "findings":
            return self._each(
                t,
                "finding",
                "ts",
                pred=lambda r: not r.get("not_executed_reason") and not _true(r.get("is_mock")),
            )
        if counter == "verdicts":
            return self._each(t, "verdict", "ts", pred=lambda r: not _true(r.get("is_mock")))
        if counter == "judge":
            return self._each(
                t,
                "verdict",
                "ts",
                pred=lambda r: int(r["tier"]) in (1, 2) and not _true(r.get("is_mock")),
            )
        if counter == "chain_lane":
            n = 0
            for a in self.agents:
                rows = t.query(
                    "chain_entry", {"lane": f"agent:{a}"}, order_by=("-seq",), limit=SCAN_CAP
                )
                n += sum(1 for r in rows if self._in(r["ts"]))
            return n
        if counter == "chain_verify":
            return self._root("chain_verify")
        if counter == "audit_pack":
            return self._root("audit_pack_built")
        if counter == "anchor":
            rows = t.query("anchor", {}, order_by=("-anchored_at",), limit=SCAN_CAP)
            return sum(1 for r in rows if self._in(r["anchored_at"]))
        if counter == "packs":
            n = 0
            for kind in ev.PACK_TARGET_KINDS:
                n += self._each(
                    t,
                    "eval_result",
                    "ts",
                    {"target_kind": kind},
                    pred=lambda r: not _true(r.get("is_mock")),
                    by="target_id",
                )
            return n
        if counter == "cases":
            return self._each(s, "cases", "opened_at")
        if counter == "signoff":
            ids = set(self._case_ids())
            n = 0
            for cid in sorted(ids):
                n += sum(1 for r in t.query("signoff", {"case_id": cid}) if self._in(r["ts"]))
            return n
        if counter == "coverage":
            return self._each(s, "coverage", None)
        if counter == "versions":
            return self._each(t, "agent_version", "deployed_at")
        if counter == "baseline":
            return self._each(s, "policy_baseline", "window_to")
        if counter == "fairness_rows":
            return self._each(t, "fairness_slice", "ts")
        if counter == "agents":
            return len(self.agents)
        if counter.startswith("mon:"):
            name = counter[4:]
            return self._monitor(None if name == "oversight" else name)
        return 0


# ------------------------------------------------------------------------------ one system


def system_agents(state: Any, system_id: str) -> list[str]:
    """The agents linked to the system (active components of kind agent), by id."""
    comps = state.query("system_component", {"system_id": system_id})
    return sorted(
        {
            str(c["ref_id"])
            for c in comps
            if c["ref_kind"] == "agent" and _true(c.get("active", True))
        }
    )


def reader_for(env: Env, system_id: str, w: ev.Window | None = None) -> Reader:
    col: ev.Collector | None
    try:
        col = env.tasks.controls().collector()
    except Exception:  # noqa: BLE001 - no deployed policy: rule controls then have no rows
        log.exception("duty evidence: no collector")
        col = None
    window = w or env.window()
    if col is None:
        col = ev.Collector(env.tables, env.state, ())
    agents, _ = col.split_agents(system_agents(env.state, system_id))
    return Reader(env, agents, window, col)


def control_rows(reader: Reader, obligation: Any, min_rows: int) -> list[dict[str, Any]]:
    """One entry per mapped Supervisor control: id, kind, coverage, counter, source, n, works."""
    out = []
    for kind, cid, cov in mapped_controls(obligation):
        counter = counter_of(kind, cid)
        n = reader.count(counter, cid if counter == "rule" else "")
        advisory = counter in ADVISORY
        measured = counter != "unmeasured"
        out.append(
            {
                "id": cid,
                "kind": kind,
                "coverage": cov,
                "counter": counter,
                "source": SOURCE_OF.get(counter, SOURCE_OF["unmeasured"])
                + (f" rule_id={cid}" if counter == "rule" else ""),
                "n": n,
                "advisory": advisory,
                "measured": measured,
                "works": bool(measured and not advisory and n >= min_rows),
            }
        )
    return out


def system_evidence(
    env: Env, system_id: str, rows: Iterable[Mapping[str, Any]], kb: Any | None = None
) -> dict[str, dict[str, Any]]:
    """``{obligation_id: {controls, mapped, works_n, all_work}}`` for the given duty rows."""
    kb = kb if kb is not None else dg.kb_of(env.settings)
    w = env.window()
    reader = reader_for(env, system_id, w)
    min_rows = int(env.settings.duty_evidence_min_rows)
    out: dict[str, dict[str, Any]] = {}
    for r in rows:
        oid = str(r["obligation_id"])
        if oid in out:
            continue
        ob = kb.obligations.get(oid)
        controls = control_rows(reader, ob, min_rows) if ob is not None else []
        works_n = sum(1 for c in controls if c["works"])
        out[oid] = {
            "controls": controls,
            "mapped": len(controls),
            "works_n": works_n,
            "all_work": bool(controls) and works_n == len(controls),
        }
    return out


def window_text(w: ev.Window) -> str:
    return f"{w.start:%Y-%m-%d}..{w.end:%Y-%m-%d}"


def counts_text(controls: Iterable[Mapping[str, Any]]) -> str:
    return ",".join(f"{c['id']}={int(c['n'])}" for c in controls)


# ------------------------------------------------------------------------------ rule (c): note


def split_note(note: Any) -> str:
    """The text after the banner: the typed close evidence or waive reason (WP-L3 stores it
    there). The earlier note (``| before: ...``) is cut off."""
    text = str(note or "")
    if text.startswith(BANNER):
        text = text[len(BANNER) :]
    return text.split(" | before:", 1)[0].strip()


def close_basis(row: Mapping[str, Any]) -> str:
    """How a row ended: ``evidence`` (closed by the system), ``person`` (closed with a control
    and an evidence reference), ``waived``, or empty while it is open."""
    if row["status"] == "waived":
        return "waived"
    if row["status"] != "closed":
        return ""
    return "evidence" if split_note(row["note"]).startswith("closed by evidence ") else "person"


# ------------------------------------------------------------------------------ rule (a): refresh


def refresh(env: Env, system: Mapping[str, Any], actor: str = ACTOR) -> dict[str, Any]:
    """Close the open ``full`` rows of the system whose mapped controls all work. Returns the
    counts and the ids closed. Safe to repeat: a closed row is not touched again."""
    sid = str(system["system_id"])
    rows = dg.rows_of(env.state, sid)
    cand = [
        r
        for r in rows
        if r["applies"] == "yes" and r["status"] == dg.OPEN_STATE and r["coverage"] == "full"
    ]
    out: dict[str, Any] = {"checked": len(cand), "closed": 0, "conflicts": 0, "ids": []}
    if not cand:
        return out
    w = env.window()
    found = system_evidence(env, sid, cand)
    day = env.clock.now().date().isoformat()
    for r in cand:
        info = found[str(r["obligation_id"])]
        if not info["all_work"]:
            continue
        cids = ",".join(sorted(c["id"] for c in info["controls"]))
        event = f"closed by evidence {window_text(w)} {counts_text(info['controls'])}"
        try:
            dg._store(  # noqa: SLF001 - the one writer of a duty row
                env,
                r,
                {
                    "status": "closed",
                    "closing_control": cids[:500],
                    "note": dg._note(event, r["note"]),
                },  # noqa: SLF001
            )
        except dg.DutyError:
            out["conflicts"] += 1
            continue
        out["closed"] += 1
        out["ids"].append(str(r["obligation_id"]))
    if out["closed"]:
        _record(env, sid, w, out, day)
    return out


def _record(env: Env, sid: str, w: ev.Window, out: Mapping[str, Any], day: str) -> None:
    """One chain record per run that closed rows: ids and integers, no text."""
    if env.sink is None:
        return
    try:
        env.sink.record(
            "duty_evidence_close",
            f"duty_evidence:{sid}:{day}",
            {
                "system_id": sid,
                "actor_ref": ACTOR,
                "window_start": format_ts(w.start),
                "window_end": format_ts(w.end),
                "rows_closed": int(out["closed"]),
                "obligation_ids": sorted(out["ids"])[:200],
                "ts": format_ts(env.clock.now()),
            },
        )
    except Exception:  # noqa: BLE001 - the rows are stored; log and go on
        log.exception("duty evidence chain record failed")


# ------------------------------------------------------------------------------ rule (b)


def group_template(instrument_id: str, coverage: str) -> str:
    from supervisor.governance.register_v2 import duties as dut

    return f"{dut.TEMPLATE_PREFIX}{instrument_id}-{coverage}"


def close_group_tasks(
    env: Env, system_id: str, keys: Iterable[tuple[str, str]], actor: str = TASK_ACTOR
) -> int:
    """For each gap group (instrument, coverage) with no open applying row left and at least one
    closed row, close the WP-L2 task of the group through the task service. Returns the number
    of tasks closed. A task that is already done or waived is left alone."""
    from supervisor.tasks.model import OPEN_STATUSES
    from supervisor.tasks.service import task_id_for

    rows = dg.rows_of(env.state, system_id)
    n = 0
    for inst, cov in sorted(set(keys)):
        grp = [r for r in rows if r["applies"] == "yes" and dg.group_key(r) == (inst, cov)]
        if not grp or any(r["status"] == dg.OPEN_STATE for r in grp):
            continue
        if not any(r["status"] == "closed" for r in grp):
            continue
        tid = task_id_for(system_id, group_template(inst, cov))
        task = env.state.get("task", {"task_id": tid})
        if task is None or task["status"] not in OPEN_STATUSES:
            continue
        env.tasks.done(tid, actor)
        done = env.state.get("task", {"task_id": tid})
        if done is not None:
            env.tasks._update(  # noqa: SLF001 - the note of a system action
                done, {"evidence_ref": f"{BANNER} all duties of the group closed"}
            )
        n += 1
    return n


# ------------------------------------------------------------------------------ the sweep


def sweep(env: Env) -> dict[str, Any]:
    """``refresh`` for every system (not archived) that has an open full row. One audit row
    (``console_action``, actor ``system``) per system where rows closed."""
    from supervisor.adapters.auth.audit import snapshot_hash, write_action

    out = {"systems": 0, "checked": 0, "closed": 0, "conflicts": 0}
    open_full: dict[str, int] = {}
    for r in env.state.query("obligation_status"):
        if r["applies"] == "yes" and r["status"] == dg.OPEN_STATE and r["coverage"] == "full":
            open_full[str(r["system_id"])] = open_full.get(str(r["system_id"]), 0) + 1
    for sysrow in env.state.query("ai_system"):
        sid = str(sysrow["system_id"])
        if sid not in open_full or sysrow["status"] == "archived":
            continue
        before = snapshot_hash(env.state, "system", sid)
        res = refresh(env, dict(sysrow))
        out["systems"] += 1
        out["checked"] += res["checked"]
        out["closed"] += res["closed"]
        out["conflicts"] += res["conflicts"]
        if res["closed"]:
            write_action(
                env.tables,
                env.clock,
                request_id=None,
                actor=None,
                permission="systems.edit",
                method="JOB",
                path="/jobs/duty_evidence_sweep",
                outcome="ok",
                target_kind="system",
                target_id=sid,
                before_hash=before,
                after_hash=snapshot_hash(env.state, "system", sid),
                detail=f"duty_evidence_close n={res['closed']}",
                actor_fallback=("system", "system", "scheduler"),
            )
    return out


# ------------------------------------------------------------------------------ the tab


def tab_rows(
    env: Env, system_id: str, rows: Iterable[Mapping[str, Any]]
) -> dict[str, dict[str, Any]]:
    """Per obligation id: ``{controls: [{id, n, works, advisory, measured}], mark}`` for the
    Duties tab. ``mark`` is ``works``, ``no_evidence`` or ``none`` (no Supervisor control)."""
    found = system_evidence(env, system_id, rows)
    out: dict[str, dict[str, Any]] = {}
    for oid, info in found.items():
        mark = "none" if not info["mapped"] else "works" if info["all_work"] else "no_evidence"
        out[oid] = {
            "mark": mark,
            "works_n": info["works_n"],
            "mapped": info["mapped"],
            "controls": [
                {k: c[k] for k in ("id", "n", "works", "advisory", "measured")}
                for c in info["controls"]
            ],
        }
    return out

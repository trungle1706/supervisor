"""Guardian tools of one agent (WP-N2): status per feature and results over a window.

Read only. Two uses:

* :func:`feature_rows` is the *Status* part of the Guardians tab and the source of the
  ``on N / of M`` figure on the My agents table.
* :func:`results` is the *Results* part: counts of what the enabled features did in a window.

Effective state of a feature for an agent follows the engines (docs/guardian-bindings.md)::

    effective = instance has it on (flag, config/detectors.yaml, the agent's policy override)
                AND the agent's guardian narrower does not list it

The narrower is the same class the gate, the judge and the monitors call
(``GuardianNarrower.off``), built with no cache, so the page and the engines cannot disagree.
Counts only: no excerpt, no masked text, no argument leaves the stores through this module.
"""

from __future__ import annotations

import datetime as dt
from collections.abc import Mapping
from typing import Any

from supervisor.console import overview_v3, readmodels
from supervisor.console.listing import ListingError
from supervisor.governance import guardians as gd

WINDOWS = {"24h": dt.timedelta(hours=24), "7d": dt.timedelta(days=7), "30d": dt.timedelta(days=30)}
DEFAULT_WINDOW = "7d"
SCAN = 5000
POLICY_RULES = "policy_rules"
# monitor slug -> key in oversight_metric.monitor_status
MONITOR_KEY = {
    "monitor_quality": "quality",
    "monitor_fairness": "fairness",
    "monitor_drift": "drift",
    "monitor_split_payment": "multiagent",
}


def parse_window(raw: str | None) -> str:
    if raw in (None, ""):
        return DEFAULT_WINDOW
    if raw not in WINDOWS:
        raise ListingError("window must be 24h, 7d or 30d")
    return str(raw)


# ------------------------------------------------------------------------------------ status


class Env:
    """What the rows of many agents share: the detector file, the mandatory detectors, the
    systems of each agent and their floors. Built once per request."""

    def __init__(self, ctx: Any) -> None:
        self.ctx = ctx
        s = ctx.settings
        self.bindings_on = gd.guardian_bindings_on(s)
        self.det = gd.detector_entries(s)
        self.slugs = gd.bindable_slugs(s)
        self.master = bool(getattr(s, "detectors_enabled", False))
        self.mandatory, _ = overview_v3.mandatory_detectors(ctx)
        self.narrower = gd.GuardianNarrower(ctx.state, s, ttl_s=0.0) if self.bindings_on else None
        self.systems_of: dict[str, list[dict[str, Any]]] = {}
        self._floor: dict[str, set[str]] = {}
        self._bind: dict[str, dict[str, Mapping[str, Any]]] = {}
        if self.bindings_on:
            names = {
                str(r["system_id"]): str(r["name"])
                for r in ctx.state.query("ai_system")
                if r["status"] != "archived"
            }
            for c in ctx.state.query("system_component", {"ref_kind": "agent"}):
                sid = str(c["system_id"])
                if gd._on(c["active"]) and sid in names:
                    self.systems_of.setdefault(str(c["ref_id"]).lower(), []).append(
                        {"system_id": sid, "name": names[sid]}
                    )
            for b in ctx.state.query("guardian_binding"):
                self._bind.setdefault(str(b["system_id"]), {})[str(b["feature_slug"])] = b

    def floor(self, system_id: str) -> set[str]:
        if system_id not in self._floor:
            try:
                self._floor[system_id] = {
                    f["slug"] for f in gd._floor(self.ctx.settings, self.ctx.state, system_id)
                }
            except Exception:  # noqa: BLE001 - no rules file: no floor, the page still renders
                self._floor[system_id] = set()
        return self._floor[system_id]

    def binding(self, system_id: str, slug: str) -> Mapping[str, Any] | None:
        return self._bind.get(system_id, {}).get(slug)


def _override(ctx: Any, agent_id: str) -> tuple[set[str], set[str]]:
    ov = overview_v3._override(ctx, agent_id)
    return set(getattr(ov, "enable", None) or ()), set(getattr(ov, "disable", None) or ())


def feature_rows(ctx: Any, agent_id: str, env: Env | None = None) -> list[dict[str, Any]]:
    """One row per guardian feature for the agent: ``slug``, ``group``, ``instance_on``,
    ``bindings`` (per linked system: name, state, who, locked), ``locked``, ``effective`` and
    ``reason`` (``flag_off``, ``file_off``, ``policy_off``, ``binding_off`` or ``""``)."""
    env = env or Env(ctx)
    s = ctx.settings
    extra, gone = _override(ctx, agent_id)
    off = env.narrower.off(agent_id) if env.narrower is not None else frozenset()
    systems = env.systems_of.get(agent_id.lower(), [])
    rows = []
    for slug in env.slugs:
        group = gd.group_of(slug)
        reason = ""
        if group == "detect":
            file_on = bool(env.det.get(slug, False))
            if slug == "document_intake":
                master = env.master and bool(getattr(s, "document_intake_enabled", False))
            else:
                master = env.master
            if not master:
                reason = "flag_off"
            elif slug in gone:
                reason = "policy_off"
            elif not (file_on or slug in extra):
                reason = "file_off"
            inst = not reason
        else:
            inst = gd.instance_on(s, slug, env.det)
            reason = "" if inst else "flag_off"
        binds = []
        locked = False
        for sy in systems:
            row = env.binding(sy["system_id"], slug)
            lock = slug in env.floor(sy["system_id"])
            locked = locked or lock
            binds.append(
                {
                    **sy,
                    "state": str(row["state"]) if row is not None else "on",
                    "default": row is None,
                    "set_by": str(row["set_by"]) if row is not None else None,
                    "locked": lock,
                }
            )
        effective = inst and slug not in off
        if inst and not effective:
            reason = "binding_off"
        rows.append(
            {
                "slug": slug,
                "group": group,
                "instance_on": inst,
                "bindings": binds,
                "no_system": env.bindings_on and not systems,
                "locked": locked,
                "effective": effective,
                "reason": reason,
                "by": next((b["set_by"] for b in binds if b["state"] == "off"), None),
            }
        )
    rows.append(  # the gate rules: always on, never bindable
        {
            "slug": POLICY_RULES,
            "group": "gate",
            "instance_on": True,
            "bindings": [],
            "no_system": False,
            "locked": True,
            "effective": True,
            "reason": "",
            "by": None,
        }
    )
    return rows


def summary(ctx: Any, agent_id: str, env: Env | None = None) -> dict[str, Any]:
    """``on`` / ``of`` counts, the floor slugs that are not effective (``below``) and the
    pill key: ``full`` (no floor slug off, at least one on), ``below_floor`` or ``none``."""
    env = env or Env(ctx)
    rows = feature_rows(ctx, agent_id, env)
    on = sum(1 for r in rows if r["effective"])
    floor = set(env.mandatory) | {
        r["slug"] for r in rows if r["locked"] and r["slug"] != POLICY_RULES
    }
    by = {r["slug"]: r for r in rows}
    below = sorted(s for s in floor if s in by and not by[s]["effective"])
    # only the detectors/gate features that are bindable can be in the floor
    on_detect = on - 1  # the gate rules are always on and do not count as a "guardian tool"
    if on_detect <= 0:
        cover = "none"
    elif below:
        cover = "below_floor"
    else:
        cover = "full"
    return {"on": on_detect, "of": len(rows) - 1, "below": below, "cover": cover}


# ----------------------------------------------------------------------------------- results


def _since(ctx: Any, window: str) -> dt.datetime:
    return ctx.clock.now() - WINDOWS[window]


def _in(rows: list[dict[str, Any]], since: dt.datetime) -> list[dict[str, Any]]:
    return [r for r in rows if isinstance(r.get("ts"), dt.datetime) and r["ts"] >= since]


def _detector_results(rows: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    out: dict[str, dict[str, Any]] = {}
    for f in rows:
        slug = str(f.get("detector_slug") or "")
        d = out.setdefault(slug, {"n": 0, "mock": 0, "codes": {}, "hints": {}})
        d["n"] += 1
        d["mock"] += 1 if f.get("is_mock") else 0
        code = str(f.get("code") or "")
        d["codes"][code] = d["codes"].get(code, 0) + 1
        hint = str(f.get("action_hint") or "")
        if hint:
            d["hints"][hint] = d["hints"].get(hint, 0) + 1
    for d in out.values():
        top = sorted(d["codes"].items(), key=lambda kv: (-kv[1], kv[0]))[:3]
        d["top"] = [{"code": c, "n": n} for c, n in top]
        d["hint_list"] = [h for h, _ in sorted(d["hints"].items(), key=lambda kv: (-kv[1], kv[0]))]
        del d["codes"], d["hints"]
    return out


def _gate_results(ctx: Any, agent_id: str, since: dt.datetime) -> dict[str, Any]:
    events = _in(
        ctx.tables.query(
            "agent_event",
            {"agent_id": agent_id, "event_type": "gate_decision"},
            order_by=("-ts",),
            limit=SCAN,
        ),
        since,
    )
    ids = {e["event_id"] for e in events}
    stops: dict[str, str] = {}
    would: set[str] = set()
    for v in _in(
        ctx.tables.query(
            "verdict", {"agent_id": agent_id, "tier": 0}, order_by=("-ts",), limit=SCAN
        ),
        since,
    ):
        key = v.get("event_id")
        if key not in ids:
            continue
        if str(v.get("label") or "").startswith("shadow_would_"):
            would.add(key)
        if not v["advisory"] and v["action"] in ("block", "pause") and stops.get(key) != "pause":
            stops[key] = v["action"]
    blocked = sum(1 for a in stops.values() if a == "block")
    paused = sum(1 for a in stops.values() if a == "pause")
    return {
        "checks": len(events),
        "allowed": max(0, len(events) - blocked - paused),
        "blocked": blocked,
        "paused": paused,
        "would_block": len(would),
    }


def _judge_results(ctx: Any, agent_id: str, since: dt.datetime) -> dict[str, dict[str, Any]]:
    verdicts = [
        v
        for v in _in(
            ctx.tables.query("verdict", {"agent_id": agent_id}, order_by=("-ts",), limit=SCAN),
            since,
        )
        if int(v.get("tier") or 0) >= 1 and v.get("role") != "protocol"
    ]
    cases = [
        c
        for c in ctx.cases.list_cases(agent_id=agent_id)
        if isinstance(c.get("opened_at"), dt.datetime) and c["opened_at"] >= since
    ]
    judge_cases = [
        c for c in cases if any(k["source_kind"] == "judge" for k in ctx.cases.links(c["case_id"]))
    ]
    out: dict[str, dict[str, Any]] = {}
    for slug, challenger in (("judge_t2_sample", False), ("judge_challenger", True)):
        mine = [v for v in verdicts if (v.get("role") == "challenger") == challenger]
        out[slug] = {
            "verdicts": len(mine),
            "mock": sum(1 for v in mine if v.get("is_mock")),
            "cases": 0 if challenger else len(judge_cases),  # a challenger never opens a case
        }
    return out


def _monitor_results(ctx: Any, agent_id: str) -> dict[str, dict[str, Any]]:
    rows = ctx.tables.query(
        "oversight_metric", {"agent_id": agent_id}, order_by=("-metric_date",), limit=30
    )
    from supervisor.console import views

    cells = (views.monitor_status_rows(rows) or [{}])[0].get("monitors", {})
    return {slug: cells[key] for slug, key in MONITOR_KEY.items() if key in cells}


def _pack_results(ctx: Any, agent_id: str) -> list[dict[str, Any]]:
    seen: dict[str, dict[str, Any]] = {}
    for r in ctx.tables.query(
        "eval_result", {"target_id": agent_id}, order_by=("-ts",), limit=SCAN
    ):
        seen.setdefault(str(r["pack_id"]), r)
    return [
        {
            "pack_id": k,
            "status": str(r["status"]),
            "ts": r["ts"],
            "is_mock": bool(r.get("is_mock")),
        }
        for k, r in sorted(seen.items())
    ]


def results(ctx: Any, agent_id: str, window: str, rows: list[dict[str, Any]]) -> dict[str, Any]:
    """Counts for the enabled features of ``rows`` (from :func:`feature_rows`) in ``window``."""
    since = _since(ctx, window)
    on = {r["slug"] for r in rows if r["effective"]}
    out: dict[str, Any] = {
        "window": window,
        "detectors": {},
        "gate": None,
        "judges": {},
        "monitors": {},
        "packs": [],
    }
    det_slugs = {r["slug"] for r in rows if r["group"] == "detect" and r["slug"] in on}
    if det_slugs:
        findings = _in(
            ctx.tables.query("finding", {"agent_id": agent_id}, order_by=("-ts",), limit=SCAN),
            since,
        )
        per = _detector_results([f for f in findings if f.get("detector_slug") in det_slugs])
        out["detectors"] = {
            s: per.get(s, {"n": 0, "mock": 0, "top": [], "hint_list": []})
            for s in sorted(det_slugs)
        }
    out["gate"] = _gate_results(ctx, agent_id, since)
    if on & {"judge_t2_sample", "judge_challenger"}:
        per_j = _judge_results(ctx, agent_id, since)
        out["judges"] = {s: per_j[s] for s in per_j if s in on}
    mon = _monitor_results(ctx, agent_id)
    out["monitors"] = {s: mon.get(s) for s in MONITOR_KEY if s in on}
    out["packs"] = _pack_results(ctx, agent_id)
    return out


def tab_data(ctx: Any, agent_id: str, query: Mapping[str, str]) -> dict[str, Any]:
    window = parse_window(query.get("window"))
    rows = feature_rows(ctx, agent_id)
    pages = readmodels.ux3_pages(ctx.settings)
    return {
        "g_rows": rows,
        "g_window": window,
        "g_windows": tuple(WINDOWS),
        "g_results": results(ctx, agent_id, window, rows),
        "g_bindings_on": gd.guardian_bindings_on(ctx.settings),
        "g_links": {
            "activity": bool(pages.get("decisions")),
            "cases": True,
            "assurance": bool(getattr(ctx.settings, "console_assurance_enabled", False)),
        },
    }

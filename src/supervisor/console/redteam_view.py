"""Read models of the red team pages (W7, flag ``REDTEAM_TAB``).

The routes (``redteam_routes.py``) stay thin. The step panel, the Red team tab, the live panel and
the report all read from ``redteam.usecase`` (the live run in memory, the stored run in the table
``redteam_usecase_run``). Nothing here writes a row.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from supervisor.console import readmodels
from supervisor.console.authz import may
from supervisor.console.i18n_redteam import FAMILY_KEYS, FIX_KEYS
from supervisor.core.canonical import parse_ts
from supervisor.redteam import usecase as uc

CAP_RULE = "GATE-AUTONOMY-CAP"
VERDICT_KIND = {"safe": "ok", "conditions": "warn", "not_safe": "bad", "not_tested": "neutral"}
RESULT_KIND = {
    "stopped": "ok",
    "got_through": "bad",
    "not_reached": "neutral",
    "kept": "ok",
    "approval": "info",
    "wrongly_stopped": "bad",
    "gave_in": "warn",
    "held": "neutral",
}


def system_of(ctx: Any, me: Any, system_id: str) -> dict[str, Any]:
    """The system when the person may see it, else a ListingError (HTTP 400)."""
    from supervisor.console.systems_views import _need_visible

    uc.check_system_id(system_id)
    return _need_visible(ctx, me, system_id)


def can_run(me: Any, system: Mapping[str, Any]) -> bool:
    return may(me, "systems.edit") and str(system.get("status") or "") != "archived"


def facts_for(ctx: Any) -> Any:
    def read(system_id: str) -> Any:
        from supervisor.onboard import orchestrator as orch

        try:
            return orch.facts_for(ctx, system_id)
        except Exception:  # noqa: BLE001 - a system whose facts cannot be read is tested from its form
            return None

    return read


def chat_of(ctx: Any) -> Any:
    """The gateway model for the AI attacker, or ``None`` when no real model is set up."""
    chat = getattr(ctx, "gate_chat", None)
    if chat is not None:
        return None if getattr(chat, "is_mock", False) else chat
    from supervisor.factory import helpers

    if not helpers.model_ready(ctx.settings):
        return None
    try:
        from supervisor.factory import runtime as rt

        return rt.gateway_model({"settings": ctx.settings})
    except Exception:  # noqa: BLE001 - no usable model: the AI attacker stays off
        return None


def run_env(ctx: Any, chat: Any = None) -> uc.RunEnv:
    return uc.RunEnv(
        ctx.state,
        ctx.clock,
        ctx.settings,
        getattr(ctx.runtime, "chain", None),
        chat,
        facts_for(ctx),
    )


# ------------------------------------------------------------------------------ formatting


def money(amount: int, lang: str) -> str:
    text = f"{int(amount):,}"
    return text.replace(",", ".") if lang == "vi" else text


def when_text(value: Any) -> str:
    """ICT date and time, no seconds."""
    if not value:
        return "-"
    try:
        dt = parse_ts(value) if isinstance(value, str) else value
        return readmodels.ict(dt).strftime("%Y-%m-%d %H:%M") + " ICT"
    except (ValueError, TypeError):
        return str(value)[:19]


def range_parts(c: Mapping[str, Any]) -> dict[str, Any]:
    """k, n and the lower end of the 95% range in whole percent (never rounded up)."""
    lo = c.get("lo")
    return {"k": c.get("k"), "n": c.get("n"), "lo": (int(lo) // 100) if lo is not None else None}


# ------------------------------------------------------------------------------ the panel


def panel_data(ctx: Any, me: Any, system_id: str, where: str = "step") -> dict[str, Any]:
    """Variables of the step panel / the tab: scope of the test, options, live or last result."""
    uc.require_on(ctx.settings)
    system = system_of(ctx, me, system_id)
    target = uc.build_target(system, facts_for(ctx)(system_id))
    active = uc.active_run_of(system_id)
    lv = uc.live(active) if active else None
    last = uc.latest_done(ctx.state, system_id)
    runs = uc.runs_of(ctx.state, system_id)
    lim = target.limits
    return {
        "rt": {
            "system": system,
            "system_id": system_id,
            "where": where if where in ("step", "tab") else "step",
            "target": target.public(),
            "tools": [n for n, _ in target.tools][:8],
            "n_tools": len(target.tools),
            "n_tested": len(target.tested_kinds()),
            "n_not_tested": sum(len(g["kinds"]) for g in target.not_tested()),
            "approval_above": lim.approval_above_vnd,
            "active": {**lv.snapshot(), "active": True, "final": "running"} if lv else None,
            "last": last,
            "last_when": when_text(last["finished_at"]) if last else "",
            "runs": [
                {
                    "run_id": r["run_id"],
                    "status": r["status"],
                    "verdict": r.get("verdict") or "",
                    "when": when_text(r.get("finished_at") or r.get("started_at")),
                }
                for r in runs
            ][:8],
            "can_run": can_run(me, system),
            "ai_ready": chat_of(ctx) is not None,
            "ai_cap": int(ctx.settings.redteam_llm_max_conversations),
            "trials": uc.TRIALS,
            "trials_default": uc.TRIALS_DEFAULT,
            "ai_counts": [
                n for n in uc.AI_COUNTS if n <= int(ctx.settings.redteam_llm_max_conversations)
            ],
            "ai_default": uc.AI_COUNT_DEFAULT,
        }
    }


def progress_data(ctx: Any, me: Any, run_id: str) -> dict[str, Any]:
    """The poll target: the live snapshot while the run goes, else the stored run."""
    uc.require_on(ctx.settings)
    uc.check_run_id(run_id)
    lv = uc.live(run_id)
    row = None
    if lv is None or lv.status != "running":
        row = uc.get_run(ctx.state, run_id)
        system_of(ctx, me, row["system_id"])
    else:
        system_of(ctx, me, lv.system_id)
    snap = lv.snapshot() if lv is not None else None
    sid = lv.system_id if lv is not None else row["system_id"]
    system = system_of(ctx, me, sid)
    active = bool(snap and snap["status"] == "running")
    if snap is None and row is not None:
        plan = (row.get("config") or {}).get("plan") or {}
        snap = {
            "run_id": run_id,
            "system_id": sid,
            "status": row["status"],
            "stage": "worst",
            "done": 0,
            "total": plan.get("total", 0),
            "percent": 0,
            "stopped": 0,
            "got_through": 0,
            "wrongly_stopped": 0,
            "kept": 0,
            "approval": 0,
            "gave_in": 0,
            "held": 0,
            "plan": plan,
            "cancel_requested": False,
            "feed": [],
            "started_at": row.get("started_at"),
        }
    assert snap is not None
    status = snap["status"] if active else (row["status"] if row else snap["status"])
    return {
        "pg": {**snap, "active": active, "final": status},
        "rt": {"system": system, "system_id": sid, "can_run": can_run(me, system)},
    }


# ------------------------------------------------------------------------------ the report


def _turns(rep: Mapping[str, Any], lang: str) -> list[dict[str, Any]]:
    out = []
    first_stop = next((t["i"] for t in rep["turns"] if t["stops"] and t["calls"]), 0)
    for t in rep["turns"]:
        calls = [
            {
                "tool": c["tool"],
                "amount": money(c["amount_minor"], lang) if "amount_minor" in c else "",
            }
            for c in t["calls"]
        ]
        out.append(
            {
                "i": t["i"],
                "user": t["user"],
                "calls": calls,
                "refused": t["refused"],
                "crossed": bool(rep["success_turn"]) and t["i"] == rep["success_turn"],
                "stops": [CAP_RULE if r == CAP_RULE else r for r in t["stops"]],
                "stopped": bool(t["stops"] and t["calls"]),
                "first_stop": t["i"] == first_stop,
            }
        )
    return out


def report_data(ctx: Any, me: Any, run_id: str, lang: str) -> dict[str, Any]:
    uc.require_on(ctx.settings)
    row = uc.get_run(ctx.state, run_id)
    system = system_of(ctx, me, row["system_id"])
    summary = row.get("summary") or {}
    done = row["status"] == "done" and bool(summary)
    out: dict[str, Any] = {
        "run": {
            "run_id": run_id,
            "status": row["status"],
            "active": run_id in uc._LIVE and uc._LIVE[run_id].status == "running",  # noqa: SLF001
            "verdict": row.get("verdict") or "",
            "started_by": row.get("started_by") or "",
            "when": when_text(row.get("finished_at") or row.get("started_at")),
            "error": row.get("error") or "",
        },
        "system": system,
        "can_run": can_run(me, system),
        "done": done,
    }
    if not done:
        return out
    a, n = summary["attacks"], summary["normal"]
    tgt = summary["target"]
    how = summary["how"]
    families = []
    for f in FAMILY_KEYS:
        c = summary["by_family"].get(f) or {}
        if not c.get("n"):
            continue
        families.append(
            {
                "key": f,
                "n": c["n"],
                "stopped": c["stopped"],
                "got_through": c["got_through"],
                "lo": (c["stop_lo"] // 100) if c.get("stop_lo") is not None else None,
                "ticks": list(c.get("ticks", "")),
                "shown": len(c.get("ticks", "")),
            }
        )
    holes = []
    for h in summary["holes"]:
        fix = h["kind"] if h["kind"] in FIX_KEYS else ("defect" if h["expected"] else "generic")
        holes.append({**h, "fix": fix, "families": h["families"]})
    replays = []
    for rep in row.get("replays") or []:
        replays.append(
            {
                "id": rep["id"],
                "stage": rep["pass"],
                "family": rep["family"],
                "kind": rep["kind"],
                "lang": rep["lang"],
                "result": rep["result"],
                "result_kind": RESULT_KIND.get(rep["result"], "neutral"),
                "success_turn": rep["success_turn"],
                "stops": rep["stops_at_success"],
                "ai": rep["attacker"] == "llm",
                "model": rep.get("attacker_model", ""),
                "turns": _turns(rep, lang),
            }
        )
    out.update(
        {
            "s": summary,
            "verdict": summary["verdict"],
            "verdict_kind": VERDICT_KIND.get(summary["verdict"], "neutral"),
            "reasons": summary["verdict_reasons"],
            "a": {**a, "lo_pct": (a["stop_lo"] // 100) if a.get("stop_lo") is not None else None},
            "normal": n,
            "mock": summary["mock_pass"],
            "families": families,
            "holes": holes,
            "not_tested": [
                {"capability": g["capability"], "kinds": g["kinds"]} for g in tgt["not_tested"]
            ],
            "rules": [
                {"rule": r, "n": c, "cap": r == CAP_RULE}
                for r, c in sorted(summary["rules"].items(), key=lambda kv: (-kv[1], kv[0]))
            ],
            "target": tgt,
            "tools": tgt["tools"],
            "limits": tgt["limits"],
            "replays": replays,
            "how": how,
            "ai": how["attacker"] == "llm",
            "approval_above": (tgt["limits"] or {}).get("approval_above_vnd"),
            "n_patterns": len(tgt["tested_kinds"]),
            "worst_n": a["n"],
        }
    )
    return out

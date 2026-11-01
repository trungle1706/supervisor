"""W8: the drift scenario for the Stability tab, in process on a temporary store.

Normal traffic builds the normal range (Stable), then the shifted traffic goes Watch to Unstable
and a drift case opens by the product's own rule. Every call goes through the real gate; the
test also scans the module for any direct write of event or metric rows."""

from __future__ import annotations

import ast
import datetime as dt
import random
from pathlib import Path
from typing import Any

import pytest

from supervisor.console import stability_view as sv
from supervisor.demo import showcase
from supervisor.demo import showcase_drift as sd
from supervisor.demo import showcase_journeys as sj

from .test_showcase_journeys import settings_for

SID = "sys-w8-demo"


@pytest.fixture(autouse=True)
def _showcase_on(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SHOWCASE_ENABLED", "1")


def make_settings(tmp_path: Path, **over: Any) -> Any:
    return settings_for(
        tmp_path / "data", drift_window_s=60, drift_settle_s=5, stability_tab=True, **over
    )


def make_system(settings: Any) -> None:
    from tests.factory.test_w4_inventory_run import mk_system

    rig = sd.open_rig(settings, None)
    try:
        mk_system(rig.ctx, SID, "Tro ly thanh toan", level="high")
    finally:
        rig.close()


def read(settings: Any) -> tuple[dict[str, Any], Any]:
    rig = sd.open_rig(settings, None)
    try:
        system = dict(rig.ctx.systems.get(SID))
        stab = sv.page_data(rig.ctx, system, {})["stab"]
        state = rig.ctx.state
        events = rig.ctx.tables.query("agent_event", {"agent_id": sd.CID})
        info = {
            "events": events,
            "bands": state.query("policy_baseline", {"agent_id": sd.CID}),
            "cases": [
                c for c in state.query("cases", {"agent_id": sd.CID}) if c["case_type"] == "drift"
            ],
            "agent": state.get("agent", {"agent_id": sd.CID}),
        }
        return stab, info
    finally:
        rig.close()


def run(
    tmp_path: Path, phases: list[tuple[sd.Profile, int]], **over: Any
) -> tuple[Any, dict[str, Any], Any]:
    settings = make_settings(tmp_path, **over)
    make_system(settings)
    lines: list[str] = []
    sent = sd.past_phase(settings, phases, seed=7, system_id=SID, say=lines.append)
    stab, info = read(settings)
    info["lines"] = lines
    info["sent"] = sent
    return stab, info, settings


# ------------------------------------------------------------------------------ the profiles


def test_profiles_are_exact_and_the_shift_is_a_real_change() -> None:
    for p in (sd.NORMAL, sd.SHIFT):
        plan = sd.plan_window(p, random.Random(1))
        assert len(plan) == p.total == 60
        assert sum(1 for t, _, _ in plan if t == "transfer") == p.transfer
        assert sum(1 for _, o, _ in plan if o == "blocked") == p.t_blocked
        amounts = [a for t, o, a in plan if t == "transfer" and o == "allowed"]
        assert len(amounts) >= 20  # the drift check needs 20 amounts in a window
    a = sd.plan_window(sd.NORMAL, random.Random(1))
    b = sd.plan_window(sd.NORMAL, random.Random(99))
    assert sorted(a) == sorted(b)  # same window, another order
    assert sd.plan_window(sd.NORMAL, random.Random(1)) == a  # repeatable


def test_blocked_calls_carry_an_injection_text_and_no_real_data() -> None:
    rng = random.Random(3)
    tool, args = sd.build("transfer", "blocked", 150_000_000, rng, 5)
    assert (
        tool == "transfer"
        and args["memo"] in sd.st.INJECTIONS
        and args["amount_minor"] == 150_000_000
    )
    tool, args = sd.build("add_payee", "masked", 0, rng, 6)
    assert tool == "add_payee" and set(args) >= {"account_number", "phone", "cccd"}


def test_the_module_never_writes_event_or_metric_rows() -> None:
    src = Path(sd.__file__).read_text()
    tables = {
        "agent_event",
        "verdict",
        "oversight_metric",
        "policy_baseline",
        "cases",
        "chain_entry",
    }
    for node in ast.walk(ast.parse(src)):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
            if node.func.attr in {"insert", "append", "update", "delete", "redact_columns"}:
                strings = {a.value for a in node.args if isinstance(a, ast.Constant)}
                assert not (strings & tables), ast.unparse(node)
    assert "subprocess" not in src and "exec(" not in src and "eval(" not in src


# ------------------------------------------------------------------------------ off paths


def test_flag_off_and_long_window_are_refused(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: Any
) -> None:
    monkeypatch.setenv("SQL_BACKEND", "sqlite")
    monkeypatch.setenv("DATA_DIR", str(tmp_path / "d"))
    monkeypatch.delenv("SHOWCASE_ENABLED", raising=False)
    assert sd.main(["baseline"]) == 2
    assert "SHOWCASE_ENABLED" in capsys.readouterr().out
    monkeypatch.setenv("SHOWCASE_ENABLED", "1")  # on, but the drift window is the default day
    assert sd.main(["baseline"]) == 2
    assert "DRIFT_WINDOW_S" in capsys.readouterr().out
    assert not (tmp_path / "d").exists() or not list((tmp_path / "d").glob("*.db"))


def test_the_dispatcher_knows_the_command(capsys: Any) -> None:
    assert "drift" in showcase.COMMANDS
    assert showcase.main([]) == 2
    assert "drift" in capsys.readouterr().out


def test_default_drift_window_and_settle_are_unchanged() -> None:
    from supervisor.config import load_settings
    from supervisor.monitors.drift import DriftConfig

    s = load_settings(sql_backend="sqlite", _env_file=None)
    assert s.drift_window_s == 86400 and s.drift_settle_s == 600
    cfg = DriftConfig.from_settings(s)
    assert cfg.window_s == 86400 and cfg.settle_s == 600
    short = DriftConfig.from_settings(
        load_settings(sql_backend="sqlite", _env_file=None, drift_settle_s=5)
    )
    assert short.settle_s == 5


# ------------------------------------------------------------------------------ the story


def test_normal_traffic_builds_the_range_and_is_stable(tmp_path: Path) -> None:
    stab, info, _ = run(tmp_path, [(sd.NORMAL, sd.BASELINE_WINDOWS)])
    assert len(info["events"]) == 9 * 60 and all(
        e["event_type"] == "gate_decision" for e in info["events"]
    )
    assert info["agent"]["gate_state"] == "RUNNING"
    assert {b["metric"] for b in info["bands"]} == {
        "amount_p50", "amount_p90", "block_rate_bp",
        "tool_share_bp:add_payee", "tool_share_bp:reconcile", "tool_share_bp:transfer",
    }  # fmt: skip
    assert all(b["window_s"] == 60 for b in info["bands"]) and info["cases"] == []
    assert stab["state"] == "stable" and stab["b"]["why"] == "ok"
    assert stab["b"]["banded"] is True and stab["b"]["bands_n"] == 6
    # the events are in the past, ending at a window edge, and the agent is in the system
    last = max(e["ts"] for e in info["events"])
    assert last <= dt.datetime.now(dt.UTC)
    assert stab["agents"] == [sd.CID]
    # a stable story has no pause and no case on the timeline, only the new normal range
    assert [e["kind"] for e in stab["timeline"]] == ["baseline"]


def test_one_shifted_window_is_watch(tmp_path: Path) -> None:
    stab, info, _ = run(tmp_path, [(sd.NORMAL, sd.BASELINE_WINDOWS), (sd.SHIFT, 1)])
    assert stab["state"] == "watch" and stab["b"]["why"] == "range", stab["b"]["names_h"]
    assert info["cases"] == []  # one window is not a case
    assert info["sent"].resumes >= 1  # the shift pauses the agent; the demo resumes it


def test_three_shifted_windows_open_a_drift_case_and_are_unstable(tmp_path: Path) -> None:
    stab, info, _ = run(tmp_path, [(sd.NORMAL, sd.BASELINE_WINDOWS), (sd.SHIFT, sd.SHIFT_WINDOWS)])
    assert len(info["cases"]) == 1 and info["cases"][0]["status"] == "open"
    assert stab["state"] == "unstable"
    kinds = [e["kind"] for e in stab["timeline"]]
    assert "case_drift" in kinds and ("pause_n" in kinds or "pause" in kinds)
    stopped = next(c for c in stab["b"]["charts"] if c["id"] == "stopped")
    assert stopped["sentence"]["key"] == "st_sent_up"
    amount = next(c for c in stab["b"]["charts"] if c["id"] == "amount")
    assert amount["sentence"]["key"] == "st_sent_up"
    # the gate decided: some calls were really stopped, none by the Stability code
    denied = [e for e in info["events"] if e["status"] == "denied"]
    assert len(denied) >= sd.SHIFT_WINDOWS * sd.SHIFT.t_blocked
    assert not any(e["status"] == "denied" for e in info["events"][: 9 * 60])


def test_a_second_past_run_refuses_to_mix_with_existing_calls(tmp_path: Path) -> None:
    settings = make_settings(tmp_path)
    make_system(settings)
    sd.past_phase(settings, [(sd.NORMAL, 2)], seed=1, system_id=SID, say=lambda _t: None)
    with pytest.raises(sj.ShowcaseError, match="traffic_exists"):
        sd.past_phase(settings, [(sd.NORMAL, 2)], seed=1, system_id=SID, say=lambda _t: None)

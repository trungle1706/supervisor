"""W8: the Stability tab (setting STABILITY_TAB): formatting, verdict rules, chart geometry, the
page data on a seeded store, the routes (off path, permission, bad input), labels in EN and VI.

Traffic is written straight into a test store (this is a unit test of the reader); the demo
scenario that goes through the real gate is tested in tests/demo/test_w8_showcase_drift.py."""

from __future__ import annotations

import ast
import re
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest

from supervisor.adapters.clock import FixedClock
from supervisor.console import i18n, i18n_stability
from supervisor.console import stability_view as sv
from supervisor.core import rbac
from supervisor.monitors.seed import event
from tests.governance.conftest import mounted, on, restore_app  # noqa: F401  (fixtures)

from .conftest import Console

NOW = datetime(2026, 11, 1, 10, 0, 30, tzinfo=UTC)  # 30 s into a one-minute window
WIN = 60
AGENT = "payments-w8"
SID = "sys-w8"
BANDS = {
    "block_rate_bp": (-300, 300),
    "amount_p50": (4_000_000, 6_000_000),
    "amount_p90": (4_000_000, 6_000_000),
    "tool_share_bp:transfer": (4000, 6000),
    "tool_share_bp:reconcile": (4000, 6000),
}


# ------------------------------------------------------------------------------ formatting


def test_formats_are_integer_arithmetic() -> None:
    assert [sv.fmt_bp(v) for v in (0, 100, 316, 900, 1660, 10000, None)] == [
        "0%",
        "1%",
        "3.1%",
        "9%",
        "16.6%",
        "100%",
        "-",
    ]
    assert [sv.fmt_vnd(v) for v in (950, 1_000, 950_000, 5_000_000, 12_500_000, 180_000_000)] == [
        "950",
        "1k",
        "950k",
        "5M",
        "12.5M",
        "180M",
    ]
    assert sv.fmt_vnd(2_000_000_000) == "2B" and sv.fmt_vnd(None) == "-"
    assert sv.fmt_ms(7) == "7 ms" and sv.fmt_ms(12_000) == "12 s"
    assert sv.window_words(60) == ("minute", 1)
    assert sv.window_words(7200) == ("hour", 2)
    assert sv.window_words(86400) == ("day", 1)
    assert sv.window_words(90) == ("second", 90)


def test_streak_skips_gaps_like_the_drift_check() -> None:
    band = {"low": 10, "high": 20}
    assert sv.streak([15, 30, 31], band) == 2
    assert sv.streak([30, None, 31, None], band) == 2  # a gap neither breaks nor extends
    assert sv.streak([30, 15], band) == 0
    assert sv.streak([30, 31], None) == 0
    assert sv.outside(None, band) is False and sv.outside(9, band) and sv.outside(21, band)


# ------------------------------------------------------------------------------ the verdict

IN = {"block_rate_bp": 0, "amount_p50": 5_000_000}
OUT = {"block_rate_bp": 1700, "amount_p50": 18_000_000}
BAND = {
    "block_rate_bp": {"low": -300, "high": 300},
    "amount_p50": {"low": 4_000_000, "high": 6_000_000},
}


def verdict(windows: list[dict[str, int | None]], **kw: Any) -> dict[str, Any]:
    args: dict[str, Any] = {"m": 3, "drift_case_open": False, "session_alert": False}
    return sv.decide(windows, BAND, **{**args, **kw})


def test_verdict_stable_when_everything_is_inside() -> None:
    v = verdict([IN, IN, IN, IN, IN])
    assert v["state"] == "stable" and v["why"] == "ok" and v["checked"] == 2


def test_verdict_watch_when_outside_in_the_latest_window() -> None:
    v = verdict([IN, IN, IN, IN, OUT])
    assert v["state"] == "watch" and v["why"] == "range"
    assert v["names"] == ["amount_p50", "block_rate_bp"]


def test_verdict_watch_on_a_conversation_alert_only() -> None:
    v = verdict([IN, IN, IN, IN, IN], session_alert=True)
    assert v["state"] == "watch" and v["why"] == "session"


def test_verdict_unstable_after_m_windows_in_a_row() -> None:
    assert verdict([IN, IN, IN, OUT, OUT])["state"] == "watch"  # two is not yet three
    v = verdict([IN, IN, OUT, OUT, OUT])
    assert v["state"] == "unstable" and v["why"] == "streak"
    assert v["streaks"]["amount_p50"] == 3
    assert verdict([IN, OUT, OUT, OUT, IN])["state"] == "stable"  # back inside: the run is over


def test_verdict_unstable_with_an_open_drift_case() -> None:
    v = verdict([IN, IN, IN, IN, IN], drift_case_open=True)
    assert v["state"] == "unstable" and v["why"] == "case"


def test_verdict_not_enough_data() -> None:
    assert sv.decide([IN] * 5, {}, m=3, drift_case_open=False, session_alert=False)["why"] == (
        "nobase"
    )
    quiet = verdict([{}, {}, {}, {}, {}])
    assert quiet["state"] == "nodata" and quiet["why"] == "quiet"
    short = {"block_rate_bp": None, "amount_p50": None}
    assert verdict([short] * 5)["state"] == "nodata"
    assert verdict([IN, {}, {}, {}, {}])["state"] == "stable"  # judged on the last window with data


def test_mock_judge_scores_never_reach_the_measures_that_decide() -> None:
    ev = [event(NOW, AGENT, "1", "gate_decision", tool="transfer", amount=1_000) for _ in range(25)]
    scores = [
        {"tier": 1, "role": "primary", "score_bp": 9000, "is_mock": True, "ts": NOW}
        for _ in range(25)
    ]
    vals = sv.bucket_values([e.row() for e in ev], scores, min_n=20, tools=["transfer"])
    assert "judge_p50_bp" not in vals  # the drift measure is real judges only
    assert vals["mock_p50_bp"] == 9000 and vals["mock_p90_bp"] == 9000
    real = [{**s, "is_mock": False} for s in scores]
    vals = sv.bucket_values([e.row() for e in ev], real, min_n=20, tools=["transfer"])
    assert vals["judge_p50_bp"] == 9000 and "mock_p50_bp" not in vals


def test_bucket_values_match_the_drift_measures() -> None:
    rows = []
    for i in range(40):
        status = "denied" if i < 4 else "allowed"
        rows.append(
            event(
                NOW, AGENT, "1", "gate_decision", tool="transfer" if i % 2 else "reconcile",
                amount=5_000_000 if i % 2 else None, status=status, latency_ms=10 + i,
            ).row()
        )  # fmt: skip
    v = sv.bucket_values(rows, [], min_n=20, tools=["transfer", "reconcile"])
    assert v["calls"] == 40 and v["block_rate_bp"] == 1000
    assert v["tool_share_bp:transfer"] == 5000 and v["amount_p50"] == 5_000_000
    assert v["gate_p50_ms"] == 29 and v["gate_p90_ms"] == 45
    few = sv.bucket_values(rows[:5], [], min_n=20, tools=["transfer"])
    assert few["calls"] == 5 and "block_rate_bp" not in few and "amount_p50" not in few


# ------------------------------------------------------------------------------ chart geometry


def series(values: list[int | None], band: dict[str, int] | None = None, breach: Any = None) -> Any:
    return {
        "key": "k",
        "values": values,
        "band": band,
        "breach": breach or [False] * len(values),
        "dash": False,
    }


def test_panel_svg_stays_inside_its_box_and_breaks_lines_at_gaps() -> None:
    labels = [f"{i:02d}:00" for i in range(6)]
    g = sv.panel_svg(
        [series([1, 2, None, 4, 5, 200], {"low": -50, "high": 3}, [0, 0, 0, 0, 0, True])],
        labels,
        "bp",
    )
    assert g["empty"] is False
    assert len(g["series"][0]["paths"]) == 2  # the gap splits the line (1-2 and 4-5-200)
    for d in g["series"][0]["dots"]:
        assert g["x0"] <= d["x"] <= g["x1"] and g["y0"] <= d["y"] <= g["y1"]
    band = g["series"][0]["band"]
    assert band["y"] >= g["y0"] - 0.1 and band["y"] + band["h"] <= g["y1"] + 0.1  # clamped at zero
    assert [t["label"] for t in g["xticks"]] == [labels[0], labels[3], labels[5]]
    assert len(g["stripes"]) == 1 and g["series"][0]["dots"][-1]["breach"] is True
    assert all(isinstance(v, float) for v in (g["series"][0]["dots"][0]["x"],))


def test_panel_svg_marks_empty_and_bar_panels() -> None:
    assert sv.panel_svg([series([None, None])], ["a", "b"], "n")["empty"] is True
    zero = sv.panel_svg([series([0, 0, 0])], ["a", "b", "c"], "n", kind="bars")
    assert zero["empty"] is True and zero["series"][0]["bars"] == []
    some = sv.panel_svg([series([0, 2, 0])], ["a", "b", "c"], "n", kind="bars")
    assert some["empty"] is False and len(some["series"][0]["bars"]) == 1


def test_sentences() -> None:
    band = {"low": 0, "high": 300}
    inside = series([100, 120, 110, None], band)
    assert sv.sentence("st_m_stopped", inside, "bp", "hour", banded=True)["key"] == "st_sent_stay"
    up = series([100, 120, 1700, 1800, 5], band, [0, 0, True, True, False])
    s = sv.sentence("st_m_stopped", up, "bp", "hour", banded=True)
    assert s["key"] == "st_sent_up" and s["params"]["a"] == "1.2%" and s["params"]["b"] == "18%"
    assert s["params"]["n"] == 2 and s["params"]["unit_key"] == "minute_many"
    down = series([5000, 100, 90, 4], {"low": 4000, "high": 6000}, [0, True, True, False])
    assert sv.sentence("st_m_x", down, "bp", "day", banded=True)["key"] == "st_sent_down"
    none = series([None, None])
    assert sv.sentence("st_m_x", none, "bp", "hour", banded=True)["key"] == "st_sent_none"
    plain = sv.sentence("st_m_x", series([100, 300, 900]), "bp", "hour", banded=False)
    assert plain["key"] == "st_sent_plain" and plain["params"]["a"] == "1%"
    assert plain["params"]["b"] == "3%"  # the last bucket is open: not used


# ------------------------------------------------------------------------------ a seeded store


class Traffic:
    """Calls for one agent in one-minute windows ending at 10:00:00; ``windows`` is oldest first."""

    def __init__(self, ctx: Any) -> None:
        self.ctx = ctx
        self.first = datetime(2026, 11, 1, 10, 0, tzinfo=UTC)

    def write(self, shapes: list[str], *, agent: str = AGENT, per: int = 30) -> None:
        rows = []
        start = self.first - timedelta(seconds=WIN * len(shapes))
        for w, shape in enumerate(shapes):
            for i in range(per):
                ts = start + timedelta(seconds=WIN * w + 1 + i)
                if shape == "-":
                    continue
                out = shape == "out"
                transfer = i % 2 == 0 if not out else i % 5 != 0
                denied = out and i < 5
                rows.append(
                    event(
                        ts, agent, "1", "gate_decision",
                        tool="transfer" if transfer else "reconcile",
                        amount=(18_000_000 if out else 5_000_000) if transfer else None,
                        status="denied" if denied else "allowed", latency_ms=8,
                    ).row()
                )  # fmt: skip
        self.ctx.tables.append("agent_event", rows)


def put_bands(ctx: Any, agent: str = AGENT, window_s: int = WIN) -> None:
    for metric, (low, high) in BANDS.items():
        ctx.state.insert(
            "policy_baseline",
            {
                "agent_id": agent,
                "agent_version": "1",
                "metric": metric,
                "baseline_id": "b1",
                "center": (low + high) // 2,
                "mad": 1,
                "band_low": low,
                "band_high": high,
                "k": 3,
                "windows": 7,
                "window_s": window_s,
                "window_from": NOW - timedelta(hours=1),
                "window_to": NOW - timedelta(minutes=50),
                "breach_streak": 0,
                "last_value": None,
                "last_checked_to": None,
                "open_case_id": None,
                "computed_at": NOW - timedelta(minutes=49),
            },
        )


def make_system(
    ctx: Any, runtime: Any, agent: str = AGENT, gate_state: str = "RUNNING"
) -> dict[str, Any]:
    from pathlib import Path as P

    from supervisor.demo.seed_systems import Manifest, _ensure_agent
    from tests.factory.test_w4_inventory_run import mk_system

    mk_system(ctx, SID, "Tro ly thanh toan", level="high")
    m = Manifest(
        system={"owner_team": "Nhom The", "owner_user": "nguoi-so-huu"},
        agent_id=agent, agent_name="Payments W8", model_family="qwen", plug_point="sdk",
        tools=(("transfer", "money"),), path=P(agent),
    )  # fmt: skip
    _ensure_agent(runtime, m)
    ctx.systems.link(SID, "agent", agent, "reviewer.an")
    if gate_state != "SHADOW":
        ctx.state.update(
            "agent", {"agent_id": agent}, {"gate_state": gate_state},
            ctx.state.get("agent", {"agent_id": agent})["row_version"],
        )  # fmt: skip
    return dict(ctx.systems.get(SID))


@pytest.fixture
def w8(on: Console, monkeypatch: pytest.MonkeyPatch) -> Console:  # noqa: F811
    console = on
    s = console.ctx.settings
    for flag in (
        "stability_tab",
        "console_nav_v3",
        "console_systems_enabled",
        "governance_enabled",
        "console_ux5",
    ):
        monkeypatch.setattr(s, flag, True)
    monkeypatch.setattr(s, "drift_window_s", WIN)
    monkeypatch.setattr(console.runtime.adapters, "clock", FixedClock(NOW))
    return console


def data(c: Console, system: dict[str, Any], **q: str) -> dict[str, Any]:
    return sv.page_data(c.ctx, system, q)["stab"]


def test_not_live_yet_is_a_calm_empty_state(w8: Console) -> None:
    system = make_system(w8.ctx, w8.runtime, gate_state="SHADOW")
    d = data(w8, system)
    assert d["state"] == "nodata" and d["b"]["why"] == "notlive" and d["b"]["has_data"] is False
    assert d["b"]["need"] == {"unit_key": "minute_many", "count": 7}  # says when it starts
    assert d["b"]["charts"] == []


def test_live_without_calls_waits(w8: Console) -> None:
    d = data(w8, make_system(w8.ctx, w8.runtime))
    assert d["state"] == "nodata" and d["b"]["why"] == "waiting"


def test_no_agent_linked(w8: Console) -> None:
    from tests.factory.test_w4_inventory_run import mk_system

    mk_system(w8.ctx, "sys-empty", "Khong co tac tu")
    d = sv.page_data(w8.ctx, dict(w8.ctx.systems.get("sys-empty")), {})["stab"]
    assert d["state"] == "nodata" and d["why"] == "noagent" and d["agents"] == []


def test_calls_without_a_normal_range_are_collecting(w8: Console) -> None:
    system = make_system(w8.ctx, w8.runtime)
    Traffic(w8.ctx).write(["in", "in", "in"])
    d = data(w8, system)
    assert d["state"] == "nodata" and d["b"]["why"] == "collecting"
    assert 0 < d["b"]["have_pct"] < 100 and d["b"]["bands_n"] == 0
    assert d["b"]["charts"], "the lines are drawn while the range is still being built"


def test_stable_when_every_window_is_inside_the_range(w8: Console) -> None:
    system = make_system(w8.ctx, w8.runtime)
    put_bands(w8.ctx)
    Traffic(w8.ctx).write(["in"] * 8)
    d = data(w8, system)
    assert (d["state"], d["b"]["why"]) == ("stable", "ok") and d["b"]["banded"] is True
    assert d["b"]["bands_n"] == 5 and d["b"]["m"] == 3


def test_watch_then_unstable_by_window_count(w8: Console) -> None:
    system = make_system(w8.ctx, w8.runtime)
    put_bands(w8.ctx)
    Traffic(w8.ctx).write(["in", "in", "in", "in", "in", "in", "in", "in", "out"])
    d = data(w8, system)
    assert d["state"] == "watch" and d["b"]["why"] == "range"
    names = {n["key"] + n["tool"] for n in d["b"]["names_h"]}
    assert {"st_m_tooltransfer", "st_m_tool" + "reconcile", "st_m_amount_p50"} <= names
    # the charts say it in words and mark the window
    amount = next(c for c in d["b"]["charts"] if c["id"] == "amount")
    assert amount["sentence"]["key"] == "st_sent_up"
    assert any(sr["dots"][-1]["breach"] for sr in amount["panels"][0]["svg"]["series"][:1])


def test_three_shifted_windows_in_a_row_are_unstable(w8: Console) -> None:
    system = make_system(w8.ctx, w8.runtime)
    put_bands(w8.ctx)
    Traffic(w8.ctx).write(["in"] * 6 + ["out", "out", "out"])
    d = data(w8, system)
    assert d["state"] == "unstable" and d["b"]["why"] == "streak"
    stopped = next(c for c in d["b"]["charts"] if c["id"] == "stopped")
    assert stopped["sentence"]["key"] == "st_sent_up"
    assert stopped["sentence"]["params"]["n"] == 3
    assert stopped["sentence"]["params"]["b"] == "16.6%"


def test_an_open_drift_case_is_unstable_and_a_closed_one_is_not(w8: Console) -> None:
    system = make_system(w8.ctx, w8.runtime)
    put_bands(w8.ctx)
    Traffic(w8.ctx).write(["in"] * 8)
    row = {
        "case_id": "case-w8-1", "agent_id": AGENT, "severity": "medium", "status": "open",
        "opened_at": NOW - timedelta(minutes=2), "regulation_refs": [],
        "summary": "Drift: test", "case_type": "drift",
    }  # fmt: skip
    w8.ctx.state.insert("cases", row)
    d = data(w8, system)
    assert d["state"] == "unstable" and d["b"]["why"] == "case"
    kinds = [e["kind"] for e in d["timeline"]]
    assert "case_drift" in kinds
    cur = w8.ctx.state.get("cases", {"case_id": "case-w8-1"})
    w8.ctx.state.update("cases", {"case_id": "case-w8-1"}, {"status": "closed"}, cur["row_version"])
    assert data(w8, system)["state"] == "stable"


def test_quiet_traffic_is_not_enough_data(w8: Console) -> None:
    system = make_system(w8.ctx, w8.runtime)
    put_bands(w8.ctx)
    Traffic(w8.ctx).write(["in", "in", "-", "-", "-", "-", "-", "-"])
    d = data(w8, system)
    assert d["state"] == "nodata" and d["b"]["why"] == "quiet"


def test_session_alert_makes_it_watch(w8: Console) -> None:
    system = make_system(w8.ctx, w8.runtime)
    put_bands(w8.ctx)
    Traffic(w8.ctx).write(["in"] * 8)
    w8.ctx.state.insert(
        "cases",
        {
            "case_id": "case-w8-s", "agent_id": AGENT, "severity": "high", "status": "open",
            "opened_at": NOW - timedelta(minutes=1), "regulation_refs": [],
            "summary": "Session", "case_type": "session_escalation",
        },
    )  # fmt: skip
    d = data(w8, system)
    assert d["state"] == "watch" and d["b"]["why"] == "session"
    alerts = next(c for c in d["b"]["charts"] if c["id"] == "session")
    assert alerts["sentence"]["key"] == "st_sent_alerts_n"


def test_band_is_drawn_only_when_the_bucket_is_the_drift_window(w8: Console) -> None:
    system = make_system(w8.ctx, w8.runtime)
    put_bands(w8.ctx)
    Traffic(w8.ctx).write(["in"] * 8)
    hour = data(w8, system, view="hour")["b"]
    day = data(w8, system, view="day")["b"]
    assert hour["banded"] is True and hour["band_note"] is False
    assert day["banded"] is False and day["band_note"] is True
    stopped = next(c for c in day["charts"] if c["id"] == "stopped")
    assert stopped["panels"][0]["svg"]["series"][0]["band"] is None
    assert stopped["sentence"]["key"] == "st_sent_plain"
    assert data(w8, system, view="day")["state"] == "stable"  # the verdict ignores the view


def test_charts_have_the_seven_panels_and_a_table_of_numbers(w8: Console) -> None:
    system = make_system(w8.ctx, w8.runtime)
    put_bands(w8.ctx)
    Traffic(w8.ctx).write(["in"] * 8)
    charts = data(w8, system)["b"]["charts"]
    assert [c["id"] for c in charts] == [
        "calls", "stopped", "amount", "latency", "mix", "judge", "session",
    ]  # fmt: skip
    assert len(next(c for c in charts if c["id"] == "mix")["panels"]) == 2  # transfer, reconcile
    for c in charts:
        for p in c["panels"]:
            assert len(p["rows"]) == 60 and c["sentence"]["key"].startswith("st_sent_")
    latency = next(c for c in charts if c["id"] == "latency")
    assert latency["note"] == "st_note_gate_latency"  # no agent latency: the gate time, said so
    judge = next(c for c in charts if c["id"] == "judge")
    assert judge["panels"][0]["svg"]["empty"] is True and judge["mock"] is False


def test_stored_values_are_integers_and_nothing_is_written(w8: Console) -> None:
    system = make_system(w8.ctx, w8.runtime)
    put_bands(w8.ctx)
    Traffic(w8.ctx).write(["in"] * 6 + ["out"] * 3)
    before = {
        t: len(w8.ctx.tables.query(t, {}) if t == "agent_event" else w8.ctx.state.query(t, {}))
        for t in ("agent_event", "cases", "gate_control", "policy_baseline", "agent")
    }
    state_before = w8.ctx.state.get("agent", {"agent_id": AGENT})["gate_state"]
    data(w8, system)
    data(w8, system, view="week")
    after = {
        t: len(w8.ctx.tables.query(t, {}) if t == "agent_event" else w8.ctx.state.query(t, {}))
        for t in before
    }
    assert after == before
    assert w8.ctx.state.get("agent", {"agent_id": AGENT})["gate_state"] == state_before
    for b in w8.ctx.state.query("policy_baseline", {"agent_id": AGENT}):
        assert isinstance(b["band_low"], int) and isinstance(b["center"], int)


def test_the_view_never_calls_a_writer() -> None:
    """Read only: the view and its routes call no insert, update, append, pause or resume on the
    store, the services or the gate."""
    writers = {"insert", "update", "append", "delete", "pause", "resume", "change_mode", "link"}
    owners = ("state", "tables", "systems", "gateway", "states", "executor", "cases", "chain")
    for name in ("stability_view.py", "stability_routes.py"):
        src = (Path(sv.__file__).parent / name).read_text()
        for node in ast.walk(ast.parse(src)):
            if (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Attribute)
                and node.func.attr in writers
                and any(o in ast.unparse(node.func.value) for o in owners)
            ):
                pytest.fail(f"{name}: writer call {ast.unparse(node.func)}")
    assert "@router.post" not in (Path(sv.__file__).parent / "stability_routes.py").read_text()


# ------------------------------------------------------------------------------ the routes

TAB = f"/console/systems/{SID}?tab=stability&lang=en"
PANEL = f"/console/systems/{SID}/stability/panel"


def test_setting_defaults_off(console: Console) -> None:
    assert console.ctx.settings.stability_tab is False
    assert console.ctx.settings.drift_settle_s == 600  # the drift check keeps its old settle time


def test_off_path_no_tab_and_every_route_is_400(
    on: Console,  # noqa: F811
    monkeypatch: Any,
) -> None:
    console = on
    s = console.ctx.settings
    for flag in ("console_nav_v3", "console_systems_enabled", "governance_enabled", "console_ux5"):
        monkeypatch.setattr(s, flag, True)
    make_system(console.ctx, console.runtime)
    page = console.get(f"/console/systems/{SID}?lang=en", user="admin.chi")
    assert page.status_code == 200 and 'data-tab="stability"' not in page.text
    for url in (TAB, PANEL, f"/console/systems/{SID}/stability"):
        got = console.get(url, user="admin.chi")
        assert got.status_code == 400, (url, got.status_code)
    assert console.get("/console/static/stab.css").status_code == 200  # the file is always served


def test_off_path_agent_page_has_no_link(console: Console) -> None:
    assert sv.agent_link(console.ctx, None, AGENT) is None


@pytest.fixture
def seeded_on(w8: Console) -> Console:
    make_system(w8.ctx, w8.runtime)
    put_bands(w8.ctx)
    Traffic(w8.ctx).write(["in"] * 6 + ["out"] * 3)
    return w8


def test_tab_page_shows_the_verdict_charts_and_timeline(seeded_on: Console) -> None:
    got = seeded_on.get(TAB, user="admin.chi")
    assert got.status_code == 200, got.text[:300]
    html = got.text
    assert 'data-tab="stability"' in html and 'data-verdict="unstable"' in html
    assert "Unstable" in html and "3 windows in a row" in html
    assert "stab.css" in html and 'data-chart="amount"' in html and 'data-section="changed"' in html
    assert html.count('<svg class="stab-svg"') >= 6
    assert "onclick" not in html and "onchange" not in html  # CSP: no inline handlers
    assert 'hx-trigger="every 10s"' in html  # live
    assert "rose from" in html  # one plain sentence per chart


def test_panel_fragment_live_and_paused(seeded_on: Console) -> None:
    live = seeded_on.get(
        f"{PANEL}?view=hour&lang=en", user="admin.chi", headers={"HX-Request": "true"}
    )
    assert live.status_code == 200 and 'data-live="1"' in live.text
    assert 'hx-trigger="every 10s"' in live.text and "<html" not in live.text
    paused = seeded_on.get(f"{PANEL}?view=hour&live=0&lang=en", user="admin.chi")
    assert paused.status_code == 200 and 'data-live="0"' in paused.text
    assert "every 10s" not in paused.text and "Resume updates" in paused.text


def test_views_and_languages(seeded_on: Console) -> None:
    for view in ("hour", "day", "week"):
        got = seeded_on.get(f"{PANEL}?view={view}&lang=en", user="admin.chi")
        assert got.status_code == 200 and f'data-view="{view}"' in got.text
    day = seeded_on.get(f"{PANEL}?view=day&lang=en", user="admin.chi").text
    assert 'data-note="band"' in day  # the shaded range is set per minute here
    vi = seeded_on.get(f"{PANEL}?view=hour&lang=vi", user="admin.chi").text
    assert "Không ổn định" in vi and "Khoảng bình thường" in vi and "1 giờ qua" in vi


def test_bad_input_is_400_never_500(seeded_on: Console) -> None:
    for q in ("view=month", "agent=nobody", "view=hour&agent=%3Cscript%3E"):
        got = seeded_on.get(f"{PANEL}?{q}", user="admin.chi")
        assert got.status_code == 400, (q, got.status_code)
    assert (
        seeded_on.get("/console/systems/nosuch/stability/panel", user="admin.chi").status_code
        == 400
    )
    assert seeded_on.get(
        "/console/systems/%3Cb%3E/stability/panel", user="admin.chi"
    ).status_code in (
        400,
        404,
    )


def test_permission_needs_the_systems_view_role(seeded_on: Console, users: dict[str, Any]) -> None:
    lacking = [u for u, p in users.items() if not rbac.allowed(p.roles, "systems.view")]
    assert seeded_on.get(PANEL, user="admin.chi").status_code == 200
    for u in lacking[:2]:
        got = seeded_on.get(PANEL, user=u)
        assert got.status_code in (401, 403), (u, got.status_code)


def test_agent_link_points_to_the_tab(seeded_on: Console) -> None:
    me = seeded_on.ctx.provider.background()
    link = sv.agent_link(seeded_on.ctx, me, AGENT)
    assert link is None or link == f"/console/systems/{SID}?tab=stability"
    assert sv.agent_link(seeded_on.ctx, me, "no-such-agent") is None


# ------------------------------------------------------------------------------ labels


def test_every_label_has_english_and_vietnamese_and_the_same_placeholders() -> None:
    assert len(i18n_stability.ST) > 90
    for key, (en, vi) in i18n_stability.ST.items():
        assert key.startswith("st_") and en.strip() and vi.strip(), key
        assert re.findall(r"{(\w+)}", en) == re.findall(r"{(\w+)}", vi) or set(
            re.findall(r"{(\w+)}", en)
        ) == set(re.findall(r"{(\w+)}", vi)), key
        assert i18n.table()[key] == (en, vi)  # merged into the console table
        assert "!" not in en, key  # copy style: no exclamation marks
        assert not re.search(r"\b[A-Z]{2,}_[A-Z_]{2,}\b", en), f"{key}: a flag name in the text"
        assert not re.search(r"/(v1|console)/", en), f"{key}: a path in the text"
    assert any(re.search(r"[ăâêôơưđ]", vi) for _, vi in i18n_stability.ST.values())


def test_every_label_the_template_and_view_ask_for_exists() -> None:
    root = Path(sv.__file__).parent
    text = (root / "templates" / "_stability_panel.html").read_text()
    keys = set(re.findall(r"t\('(st_[a-z0-9_]+)'", text))
    keys |= set(re.findall(r"\"(st_[a-z0-9_]+)\"", (root / "stability_view.py").read_text()))
    missing = sorted(k for k in keys if k not in i18n_stability.ST and not k.endswith("_"))
    assert not missing, missing
    for unit in ("minute", "hour", "day", "second"):
        for n in ("one", "many"):
            assert f"st_u_{unit}_{n}" in i18n_stability.ST
    for state in sv.STATES:
        assert f"st_v_{state}" in i18n_stability.ST
    for ev in ("case_drift", "case_session", "case", "pause", "pause_n", "quarantine", "incident"):
        assert f"st_ev_{ev}" in i18n_stability.ST
    for why in ("ok", "range", "session", "streak", "case", "nobase", "collecting", "quiet"):
        assert f"st_why_{why}" in i18n_stability.ST
    for why in ("waiting", "notlive", "noagent"):
        assert f"st_why_{why}" in i18n_stability.ST

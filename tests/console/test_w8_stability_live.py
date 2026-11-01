"""W8 follow-up: the short demo drift window (10 to 59 s, SHOWCASE_ENABLED only) and the Live range
of the Stability tab. With a window under a minute the default range is "Live": one point per drift
window, so the band and the breach marks show; the panel refreshes every 5 seconds."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

import pytest

from supervisor.adapters.clock import FixedClock
from supervisor.config import ConfigError, load_settings
from supervisor.console import stability_view as sv
from supervisor.monitors.seed import event
from tests.governance.conftest import mounted, on, restore_app  # noqa: F401  (fixtures)

from .conftest import Console
from .test_w8_stability import AGENT, BANDS, SID, make_system, put_bands

NOW10 = datetime(2026, 11, 1, 10, 0, 5, tzinfo=UTC)  # 5 s into a ten-second window
WIN10 = 10
PANEL = f"/console/systems/{SID}/stability/panel"

# ------------------------------------------------------------------------------ the floor


def test_floor_is_60_without_showcase_and_10_with_it() -> None:
    assert load_settings(sql_backend="sqlite", _env_file=None).drift_window_s == 86400  # default
    for seconds in (10, 15, 59):
        with pytest.raises(ConfigError, match="SHOWCASE_ENABLED"):
            load_settings(sql_backend="sqlite", _env_file=None, drift_window_s=seconds)
    assert (
        load_settings(sql_backend="sqlite", _env_file=None, drift_window_s=60).drift_window_s == 60
    )
    short = load_settings(
        sql_backend="sqlite", _env_file=None, drift_window_s=10, showcase_enabled=True
    )
    assert short.drift_window_s == 10
    with pytest.raises(ConfigError):  # 10 stays the lowest, even for the demo
        load_settings(sql_backend="sqlite", _env_file=None, drift_window_s=9, showcase_enabled=True)


def test_the_env_variable_follows_the_same_rule(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DRIFT_WINDOW_S", "10")
    monkeypatch.delenv("SHOWCASE_ENABLED", raising=False)
    with pytest.raises(ConfigError):
        load_settings(sql_backend="sqlite", _env_file=None)
    monkeypatch.setenv("SHOWCASE_ENABLED", "1")
    assert load_settings(sql_backend="sqlite", _env_file=None).drift_window_s == 10


# ------------------------------------------------------------------------------ the range choice


def test_range_choice_follows_the_drift_window() -> None:
    assert sv.view_for_window(10) == "live" and sv.view_for_window(59) == "live"
    assert [sv.view_for_window(w) for w in (60, 3600, 86400, 7200)] == [
        "hour", "day", "week", "day",
    ]  # fmt: skip
    assert sv.views_for(10) == ("live", "hour", "day", "week")
    assert sv.views_for(60) == ("hour", "day", "week")  # no Live range with a normal window
    assert sv.spec("live", 10) == (10, 60)  # ten minutes of ten-second windows
    assert sv.spec("live", 15) == (15, 40)
    assert sv.spec("live", 45) == (45, 13)
    assert sv.spec("live", 59)[1] >= 8
    assert sv.spec("hour", 10) == (60, 60) and sv.spec("week", 10) == (86400, 7)


def test_parse_query_refuses_live_on_a_normal_window() -> None:
    assert sv.parse_query({}, ["a"], 10)[0] == "live"
    assert sv.parse_query({"view": "hour"}, ["a"], 10)[0] == "hour"
    assert sv.parse_query({}, ["a"], 60)[0] == "hour"
    with pytest.raises(sv.StabilityError):
        sv.parse_query({"view": "live"}, ["a"], 60)


# ------------------------------------------------------------------------------ a seeded store


def write10(ctx: Any, shapes: list[str], per: int = 30) -> None:
    """Windows of ten seconds ending at 10:00:00, oldest first: in, out or a gap."""
    rows = []
    start = datetime(2026, 11, 1, 10, 0, tzinfo=UTC) - timedelta(seconds=WIN10 * len(shapes))
    for w, shape in enumerate(shapes):
        if shape == "-":
            continue
        for i in range(per):
            out = shape == "out"
            transfer = i % 2 == 0 if not out else i % 5 != 0
            rows.append(
                event(
                    start + timedelta(seconds=WIN10 * w + i / 4), AGENT, "1", "gate_decision",
                    tool="transfer" if transfer else "reconcile",
                    amount=(18_000_000 if out else 5_000_000) if transfer else None,
                    status="denied" if out and i < 5 else "allowed", latency_ms=8,
                ).row()
            )  # fmt: skip
    ctx.tables.append("agent_event", rows)


@pytest.fixture
def w10(on: Console, monkeypatch: pytest.MonkeyPatch) -> Console:  # noqa: F811
    s = on.ctx.settings
    for flag in (
        "stability_tab", "console_nav_v3", "console_systems_enabled", "governance_enabled",
        "console_ux5", "showcase_enabled",
    ):  # fmt: skip
        monkeypatch.setattr(s, flag, True)
    monkeypatch.setattr(s, "drift_window_s", WIN10)
    monkeypatch.setattr(on.runtime.adapters, "clock", FixedClock(NOW10))
    make_system(on.ctx, on.runtime)
    put_bands(on.ctx, window_s=WIN10)
    return on


def data(c: Console, **q: str) -> dict[str, Any]:
    system = dict(c.ctx.systems.get(SID))
    return sv.page_data(c.ctx, system, q)["stab"]


def test_live_is_the_default_and_shows_the_band_and_the_breaks(w10: Console) -> None:
    write10(w10.ctx, ["in"] * 6 + ["out", "out", "out"])
    d = data(w10)
    assert d["view"] == "live" and d["views"][0] == "live" and d["refresh_s"] == 5
    assert d["live_s"] == 10
    b = d["b"]
    assert b["banded"] is True and b["band_note"] is False  # the bucket is the drift window
    assert (d["state"], b["why"]) == ("unstable", "streak")
    stopped = next(c for c in b["charts"] if c["id"] == "stopped")
    svg = stopped["panels"][0]["svg"]
    assert svg["series"][0]["band"] is not None and len(svg["stripes"]) >= 3
    assert sum(1 for d_ in svg["series"][0]["dots"] if d_["breach"]) >= 3
    assert stopped["sentence"]["key"] == "st_sent_up" and stopped["sentence"]["params"]["n"] == 3
    assert stopped["sentence"]["params"]["unit_key"] == "window_many"
    labels = [r["label"] for r in stopped["panels"][0]["rows"]]
    assert len(labels) == 60 and labels[0].count(":") == 2  # HH:MM:SS


def test_stable_on_the_short_window(w10: Console) -> None:
    write10(w10.ctx, ["in"] * 8)
    d = data(w10)
    assert (d["state"], d["b"]["why"]) == ("stable", "ok") and d["view"] == "live"


def test_one_shifted_window_is_watch(w10: Console) -> None:
    write10(w10.ctx, ["in"] * 7 + ["out"])
    assert data(w10)["state"] == "watch"


def test_two_shifted_windows_are_watch_not_unstable(w10: Console) -> None:
    write10(w10.ctx, ["in"] * 6 + ["out", "out"])
    d = data(w10)
    assert d["state"] == "watch" and d["b"]["why"] == "range"


def test_hour_range_with_a_ten_second_window_has_no_band_but_says_why(w10: Console) -> None:
    write10(w10.ctx, ["in"] * 8)
    hour = data(w10, view="hour")["b"]
    assert hour["banded"] is False and hour["band_note"] is True
    assert data(w10, view="hour")["state"] == "stable"  # the verdict ignores the range
    with pytest.raises(sv.StabilityError):
        sv.parse_query({"view": "month"}, [AGENT], 10)


def test_panel_refreshes_every_5_seconds_in_live_and_10_elsewhere(w10: Console) -> None:
    write10(w10.ctx, ["in"] * 8)
    live = w10.get(f"{PANEL}?lang=en", user="admin.chi")
    assert live.status_code == 200 and 'data-view="live"' in live.text
    assert 'hx-trigger="every 5s"' in live.text and "updates every 5 seconds" in live.text
    assert "10-second windows" in live.text and 'data-view-pick="live"' in live.text
    hour = w10.get(f"{PANEL}?view=hour&lang=en", user="admin.chi")
    assert 'hx-trigger="every 10s"' in hour.text and "updates every 10 seconds" in hour.text
    paused = w10.get(f"{PANEL}?view=live&live=0&lang=en", user="admin.chi")
    assert "every 5s" not in paused.text and "Resume updates" in paused.text
    vi = w10.get(f"{PANEL}?lang=vi", user="admin.chi").text
    assert "Trực tiếp" in vi and "khung 10 giây" in vi


def test_live_range_is_400_when_the_window_is_a_minute(
    on: Console,  # noqa: F811
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    s = on.ctx.settings
    for flag in (
        "stability_tab",
        "console_nav_v3",
        "console_systems_enabled",
        "governance_enabled",
    ):
        monkeypatch.setattr(s, flag, True)
    monkeypatch.setattr(on.runtime.adapters, "clock", FixedClock(NOW10))
    make_system(on.ctx, on.runtime)
    put_bands(on.ctx, window_s=60)
    got = on.get(f"{PANEL}?view=live", user="admin.chi")
    assert got.status_code == 400
    assert 'data-view-pick="live"' not in on.get(f"{PANEL}", user="admin.chi").text
    assert set(BANDS) and on.get(f"{PANEL}?view=hour", user="admin.chi").status_code == 200

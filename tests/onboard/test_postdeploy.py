"""WP-O5 (phase 9): the post-deploy assessment on synthetic rows. Gate statistics (calls, allowed,
blocked, would-block by rule, top 5), judge verdicts by tier with mock verdicts counted apart,
drift and session monitor status, incidents, pack re-runs on traces, the timeline (order and cap),
integers only, the window, and the flag off path."""

from __future__ import annotations

import datetime as dt
from collections.abc import Iterator
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from supervisor.adapters.factory import Adapters, build_adapters
from supervisor.config import load_settings
from supervisor.core.schema import load_model
from supervisor.jobs import bootstrap_schema
from supervisor.onboard import agent_log, postdeploy
from supervisor.onboard.postdeploy import PostdeployError

AGENT = "payments"
MODEL = load_model()


@pytest.fixture
def adapters(tmp_path: Path) -> Iterator[Adapters]:
    settings = load_settings(
        sql_backend="sqlite",
        data_dir=tmp_path / "data",
        llm_base_url="",
        onboard_postdeploy=True,
    )
    a = build_adapters(settings)
    bootstrap_schema.run(a.settings, a)
    try:
        yield a
    finally:
        a.close()


@pytest.fixture
def ctx(adapters: Adapters) -> Any:
    return SimpleNamespace(
        settings=adapters.settings,
        state=adapters.state,
        tables=adapters.tables,
        clock=adapters.clock,
    )


def row(table: str, **values: Any) -> dict[str, Any]:
    """A full row of ``table``: the given values, a typed default for every other column."""
    defaults: dict[str, Any] = {
        "string": "x",
        "text": "x",
        "int": 0,
        "bool": False,
        "json": "{}",
        "money": 0,
        "date": dt.date(2026, 10, 1),
        "timestamp": dt.datetime(2026, 10, 1, tzinfo=dt.UTC),
    }
    out: dict[str, Any] = {}
    for col in MODEL.table(table).columns:
        if col.name in values:
            out[col.name] = values[col.name]
        elif col.nullable:
            out[col.name] = None
        else:
            out[col.name] = defaults[col.type.rstrip("?")]
    return out


class Rows:
    def __init__(self, ctx: Any) -> None:
        self.ctx = ctx
        self.now = ctx.clock.now()
        self.n = 0

    def ago(self, days: int = 0, hours: int = 0, minutes: int = 0) -> dt.datetime:
        return self.now - dt.timedelta(days=days, hours=hours, minutes=minutes)

    def uid(self, prefix: str) -> str:
        self.n += 1
        return f"{prefix}{self.n:06d}"

    def add(self, table: str, **values: Any) -> None:
        full = row(table, **values)
        if MODEL.table(table).kind == "state":
            self.ctx.state.insert(table, full)
        else:
            self.ctx.tables.append(table, [full])

    def decision(self, ts: dt.datetime, agent: str = AGENT) -> str:
        eid = self.uid("e")
        self.add("agent_event", event_id=eid, ts=ts, agent_id=agent, event_type="gate_decision")
        return eid

    def gate_verdict(
        self,
        eid: str,
        ts: dt.datetime,
        rule: str,
        *,
        would: bool = False,
        stop: str | None = None,
    ) -> None:
        self.add(
            "verdict",
            verdict_id=self.uid("v"),
            ts=ts,
            event_id=eid,
            agent_id=AGENT,
            tier=0,
            rule_id=rule,
            advisory=would,
            label="shadow_would_block" if would else "matched",
            action=stop or "log",
        )

    def judge(
        self,
        ts: dt.datetime,
        tier: int,
        *,
        label: str = "benign",
        action: str = "log",
        mock: bool = False,
        role: str | None = None,
    ) -> None:
        self.add(
            "verdict",
            verdict_id=self.uid("v"),
            ts=ts,
            agent_id=AGENT,
            tier=tier,
            label=label,
            action=action,
            is_mock=mock,
            role=role,
            advisory=True,
        )


def walk(value: Any) -> list[Any]:
    if isinstance(value, dict):
        return [x for v in value.values() for x in walk(v)]
    if isinstance(value, list | tuple):
        return [x for v in value for x in walk(v)]
    return [value]


# ------------------------------------------------------------------------------ flag, days


def test_flag_defaults_off_and_require_on_says_postdeploy_off() -> None:
    s = load_settings(sql_backend="sqlite")
    assert s.onboard_postdeploy is False
    with pytest.raises(PostdeployError) as e:
        postdeploy.require_on(s)
    assert e.value.code == "postdeploy_off" and "postdeploy_off" in str(e.value)


@pytest.mark.parametrize("raw", ["0", "91", "-1", "abc", "1.5"])
def test_bad_days_are_refused_with_a_code(raw: str) -> None:
    with pytest.raises(PostdeployError) as e:
        postdeploy.parse_days(raw)
    assert e.value.code == "bad_days"


def test_days_default_and_bounds() -> None:
    assert postdeploy.parse_days(None) == 7 and postdeploy.parse_days("") == 7
    assert postdeploy.parse_days("1") == 1 and postdeploy.parse_days("90") == 90


# ------------------------------------------------------------------------------ the gate


def test_gate_statistics_from_synthetic_rows(ctx: Any) -> None:
    r = Rows(ctx)
    eids = [r.decision(r.ago(hours=i + 1)) for i in range(8)]
    r.gate_verdict(eids[0], r.ago(hours=1), "PAY-01", would=True)
    r.gate_verdict(eids[1], r.ago(hours=2), "PAY-01", would=True)
    r.gate_verdict(eids[2], r.ago(hours=3), "PAY-02", would=True)
    r.gate_verdict(eids[3], r.ago(hours=4), "PAY-03", stop="block")
    r.gate_verdict(eids[4], r.ago(hours=5), "PAY-01", stop="block")
    r.gate_verdict(eids[5], r.ago(hours=6), "PAY-04", stop="pause")
    r.decision(r.ago(days=20))  # outside the window
    got = postdeploy.assess(ctx, AGENT)
    g = got["gate"]
    assert g["checks"] == 8 and g["would_block"] == 3 and g["blocked"] == 2 and g["paused"] == 1
    assert g["allowed"] == 8 - 2 - 1
    by = {x["rule_id"]: x for x in g["by_rule"]}
    assert by["PAY-01"] == {"rule_id": "PAY-01", "would_block": 2, "blocked": 1}
    assert by["PAY-02"]["would_block"] == 1 and by["PAY-03"]["blocked"] == 1
    assert g["by_rule"][0]["rule_id"] == "PAY-01"  # the most active rule first


def test_top_rules_are_five_and_sorted_by_count_then_id(ctx: Any) -> None:
    r = Rows(ctx)
    for rule, n in [
        ("R-7", 1),
        ("R-6", 2),
        ("R-5", 3),
        ("R-4", 3),
        ("R-3", 4),
        ("R-2", 5),
        ("R-1", 6),
    ]:
        for _ in range(n):
            r.gate_verdict(r.decision(r.ago(hours=1)), r.ago(hours=1), rule, would=True)
    top = postdeploy.assess(ctx, AGENT)["gate"]["by_rule"]
    assert [x["rule_id"] for x in top] == ["R-1", "R-2", "R-3", "R-4", "R-5"]
    assert len(top) == 5


def test_mode_follows_the_agent_row_and_none_without_one(ctx: Any) -> None:
    assert postdeploy.assess(ctx, "ghost")["mode"] == "none"
    r = Rows(ctx)
    r.add("agent", agent_id=AGENT, gate_state="SHADOW", status="shadow")
    assert postdeploy.assess(ctx, AGENT)["mode"] == "shadow"


# ------------------------------------------------------------------------------ the judges


def test_judge_verdicts_by_tier_with_mock_counted_apart(ctx: Any) -> None:
    r = Rows(ctx)
    r.judge(r.ago(hours=1), 1)  # real, not flagged
    r.judge(r.ago(hours=2), 1, label="prompt_injection", action="log")  # real, flagged by label
    r.judge(r.ago(hours=3), 2, label="benign", action="open_case")  # real, flagged by action
    r.judge(r.ago(hours=4), 2)
    r.judge(r.ago(hours=5), 2, mock=True)  # mock, not flagged
    r.judge(r.ago(hours=6), 2, mock=True, label="fraud", action="alert")  # mock, flagged
    r.judge(r.ago(hours=7), 1, mock=True, label="fraud")  # mock, flagged
    r.judge(r.ago(hours=8), 2, role="protocol", label="fraud")  # protocol rows are not verdicts
    r.judge(r.ago(days=30), 2, label="fraud")  # outside the window
    j = postdeploy.assess(ctx, AGENT)["judges"]
    tiers = {t["tier"]: t for t in j["tiers"]}
    assert tiers[1] == {"tier": 1, "count": 2, "flagged": 1, "mock_count": 1, "mock_flagged": 1}
    assert tiers[2] == {"tier": 2, "count": 2, "flagged": 1, "mock_count": 2, "mock_flagged": 1}
    # a mock verdict never raises the real counts
    assert (j["count"], j["flagged"], j["mock_count"], j["mock_flagged"]) == (4, 2, 3, 2)


# ------------------------------------------------------------------------------ monitors


def test_drift_and_session_status_come_from_the_newest_day(ctx: Any) -> None:
    r = Rows(ctx)
    today = r.now.date()
    r.add(
        "oversight_metric",
        metric_date=today - dt.timedelta(days=3),
        agent_id=AGENT,
        computed_at=r.ago(days=3),
        monitor_status='{"drift": {"status": "no_data", "code": "old", "n": 1}}',
    )
    r.add(
        "oversight_metric",
        metric_date=today - dt.timedelta(days=1),
        agent_id=AGENT,
        computed_at=r.ago(days=1),
        monitor_status='{"drift": {"status": "ok", "code": "stable", "n": 42},'
        ' "session": {"status": "ok", "n": 7}, "quality": {"status": "ok"}}',
    )
    d = postdeploy.assess(ctx, AGENT)["drift"]
    assert d["drift"]["status"] == "ok" and d["drift"]["n"] == 42 and d["drift"]["code"] == "stable"
    assert d["session"]["status"] == "ok" and d["session"]["n"] == 7
    assert set(d) == {"drift", "session"}


def test_no_monitor_rows_give_none(ctx: Any) -> None:
    assert postdeploy.assess(ctx, AGENT)["drift"] == {"drift": None, "session": None}


# ------------------------------------------------------------------------------ incidents


def test_incidents_open_opened_and_closed(ctx: Any) -> None:
    r = Rows(ctx)
    r.add("incident", incident_id="inc_1", agent_id=AGENT, status="open", opened_at=r.ago(days=1))
    r.add(
        "incident",
        incident_id="inc_2",
        agent_id=AGENT,
        status="investigating",
        opened_at=r.ago(days=2),
    )
    r.add(
        "incident",
        incident_id="inc_3",
        agent_id=AGENT,
        status="closed",
        opened_at=r.ago(days=5),
        closed_at=r.ago(days=2),
    )
    r.add(
        "incident",
        incident_id="inc_4",
        agent_id=AGENT,
        status="resolved",
        opened_at=r.ago(days=40),
        closed_at=r.ago(days=30),
    )
    r.add("incident", incident_id="inc_5", agent_id="other", status="open", opened_at=r.ago(days=1))
    inc = postdeploy.assess(ctx, AGENT)["incidents"]
    assert inc == {"open": 2, "opened": 3, "closed": 1}


# ------------------------------------------------------------------------------ packs on traces


def test_pack_reruns_on_traces_keep_the_newest_per_pack(ctx: Any) -> None:
    r = Rows(ctx)

    def pack(
        pid: str, ts: dt.datetime, status: str, kind: str = "traces", mock: bool = False
    ) -> None:
        r.add(
            "eval_result",
            run_id=r.uid("r"),
            ts=ts,
            pack_id=pid,
            target_kind=kind,
            target_id=AGENT,
            status=status,
            n_items=12,
            is_mock=mock,
        )

    pack("pii_leak", r.ago(days=3), "fail")
    pack("pii_leak", r.ago(days=1), "ok")  # newer wins
    pack("drift_check", r.ago(days=2), "warn", mock=True)
    pack("jailbreak", r.ago(days=1), "ok", kind="agent")  # a launch run, not a re-run on traces
    packs = {p["pack_id"]: p for p in postdeploy.assess(ctx, AGENT)["packs"]}
    assert set(packs) == {"pii_leak", "drift_check"}
    assert packs["pii_leak"]["status"] == "ok" and packs["pii_leak"]["n_items"] == 12
    assert packs["drift_check"]["is_mock"] is True


# ------------------------------------------------------------------------------ the timeline


def test_timeline_has_every_kind_newest_first(ctx: Any) -> None:
    r = Rows(ctx)
    r.gate_verdict(r.decision(r.ago(hours=1)), r.ago(hours=1), "PAY-01", would=True)
    r.judge(r.ago(hours=2), 2, label="fraud", action="open_case")
    r.add(
        "finding",
        finding_id=r.uid("f"),
        ts=r.ago(hours=3),
        agent_id=AGENT,
        detector_slug="dlp_vn",
        code="pii.phone",
        action_hint="report",
    )
    r.add("cases", case_id="case_1", agent_id=AGENT, severity="high", opened_at=r.ago(hours=4))
    r.add("incident", incident_id="inc_1", agent_id=AGENT, status="open", opened_at=r.ago(hours=5))
    r.add(
        "eval_result",
        run_id="run_1",
        ts=r.ago(hours=6),
        pack_id="pii_leak",
        target_kind="traces",
        target_id=AGENT,
        status="ok",
    )
    r.add(
        "gate_control",
        control_id="gc_1",
        agent_id=AGENT,
        action="request_running",
        status="pending",
        created_at=r.ago(hours=7),
    )
    agent_log.log(ctx, AGENT, "predeploy", "verdict go", "report pdr_1", "rule", "rule")
    tl = postdeploy.assess(ctx, AGENT)["timeline"]
    kinds = [e["kind"] for e in tl]
    assert set(kinds) == set(postdeploy.KINDS)
    stamps = [e["ts"] for e in tl]
    assert stamps == sorted(stamps, reverse=True)
    assert kinds[0] == "agent_log"  # written just now
    assert all(set(e) == {"ts", "kind", "text", "ref"} for e in tl)


def test_timeline_is_capped_at_200_and_keeps_the_newest(ctx: Any) -> None:
    r = Rows(ctx)
    for i in range(150):
        r.add(
            "finding",
            finding_id=r.uid("f"),
            ts=r.ago(minutes=i + 1),
            agent_id=AGENT,
            detector_slug="dlp_vn",
            code="pii.phone",
            action_hint="report",
        )
    for i in range(150):
        r.judge(r.ago(days=1, minutes=i), 2, label="fraud", action="alert")
    got = postdeploy.assess(ctx, AGENT)
    assert len(got["timeline"]) == postdeploy.TIMELINE_CAP == 200
    stamps = [e["ts"] for e in got["timeline"]]
    assert stamps == sorted(stamps, reverse=True)
    # the 150 findings are the newest events: every one of them is kept
    assert sum(1 for e in got["timeline"] if e["kind"] == "finding") == 150


def test_the_window_cuts_the_timeline_and_the_counts(ctx: Any) -> None:
    r = Rows(ctx)
    r.judge(r.ago(days=2), 2, label="fraud", action="alert")
    r.judge(r.ago(days=10), 2, label="fraud", action="alert")
    assert postdeploy.assess(ctx, AGENT, days=7)["judges"]["flagged"] == 1
    assert postdeploy.assess(ctx, AGENT, days=30)["judges"]["flagged"] == 2
    assert len(postdeploy.assess(ctx, AGENT, days=1)["timeline"]) == 0
    assert postdeploy.assess(ctx, AGENT, days=30)["days"] == 30


# ------------------------------------------------------------------------------ integers only


def test_the_result_holds_no_float_and_no_personal_text(ctx: Any) -> None:
    r = Rows(ctx)
    eid = r.decision(r.ago(hours=1))
    r.gate_verdict(eid, r.ago(hours=1), "PAY-01", would=True)
    r.add(
        "verdict",
        verdict_id=r.uid("v"),
        ts=r.ago(hours=1),
        agent_id=AGENT,
        tier=2,
        score=0.73,  # the float score column exists; it must not leave this module
        score_bp=7300,
        label="fraud",
        action="alert",
        rationale_masked="Nguyễn Văn Anh 0912345678",
        advisory=True,
    )
    r.add(
        "finding",
        finding_id=r.uid("f"),
        ts=r.ago(hours=1),
        agent_id=AGENT,
        detector_slug="dlp_vn",
        code="pii.phone",
        action_hint="report",
    )
    got = postdeploy.assess(ctx, AGENT)
    assert not [v for v in walk(got) if isinstance(v, float)]
    blob = repr(got)
    assert "0912345678" not in blob and "Văn Anh" not in blob


def test_assess_reads_only_it_writes_no_row(ctx: Any) -> None:
    before = len(ctx.tables.query("onboard_log"))
    postdeploy.assess(ctx, AGENT)
    assert len(ctx.tables.query("onboard_log")) == before

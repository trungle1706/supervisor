"""WP-L4: effectiveness evidence per duty (REGULATOR_PACK).

Counts per control from synthetic rows, the works threshold, auto-close of full-coverage rows only
when all mapped controls work, no auto-close of partial or none, the group task closing with the
last row, the sweep (idempotent, audited with actor system), the Refresh evidence button (two
audit rows), the Duties tab marks, and the flag-off path. Real RegKB obligation ids; synthetic
evidence rows."""

from __future__ import annotations

import datetime as dt
from typing import Any

import pytest

from supervisor.config import load_settings
from supervisor.core import rbac
from supervisor.core.errors import ConfigError
from supervisor.governance import duties_gap as dg
from supervisor.governance import duty_evidence as de
from supervisor.risk import evidence as ev

from .conftest import Console, person
from .l4_support import (
    AGENT,
    BANNER,
    CREATOR,
    OB_CHAIN,
    OB_CONSOLE,
    OB_GATE2,
    OB_JUDGE,
    OB_MASK,
    OB_MIXED,
    OB_RULE,
    env,
    gap_task,
    gate_events,
    kb,
    put_row,
    row,
    system_with_agent,
    verdicts,
    when,
)
from .test_l3_duties import _audit, _control, _ids, _tab, _url

EVIDENCE = "DOC-2026-114 section 3"


@pytest.fixture
def l4(on: Console, monkeypatch: pytest.MonkeyPatch) -> Console:
    for flag in ("risk_duties", "risk_register_enabled", "regulator_pack"):
        monkeypatch.setattr(on.ctx.settings, flag, True)
    return on


def _counts(c: Console, sid: str, oid: str) -> dict[str, int]:
    found = de.system_evidence(env(c), sid, [{"obligation_id": oid}])[oid]
    return {x["id"]: x["n"] for x in found["controls"]}


# ------------------------------------------------------------------ flags and settings


def test_flag_defaults_and_validators() -> None:
    s = load_settings(llm_base_url="")
    assert s.regulator_pack is False
    assert s.duty_evidence_window_days == 30 and s.duty_evidence_min_rows == 1
    assert s.duty_evidence_sweep_s == 0
    assert de.enabled(s) is False and de.sweep_enabled(s) is False
    assert load_settings(llm_base_url="", duty_evidence_sweep_s=300).duty_evidence_sweep_s == 300
    with pytest.raises(ConfigError):
        load_settings(llm_base_url="", duty_evidence_sweep_s=120)


def test_flag_needs_governance_and_risk_duties(console: Console, monkeypatch: Any) -> None:
    s = console.ctx.settings
    monkeypatch.setattr(s, "regulator_pack", True)
    assert de.enabled(s) is False  # GOVERNANCE_ENABLED and RISK_DUTIES are off
    monkeypatch.setattr(s, "governance_enabled", True)
    monkeypatch.setattr(s, "console_systems_enabled", True)
    assert de.enabled(s) is False  # RISK_DUTIES is off
    monkeypatch.setattr(s, "risk_duties", True)
    assert de.enabled(s) is True
    with pytest.raises(dg.DutyError, match="regulator_pack_off"):
        de.ensure_on(load_settings(llm_base_url=""))


def test_rbac_rows_exist() -> None:
    assert (
        rbac.route_entry("POST", "/console/systems/{system_id}/duties/refresh-evidence")
        == "systems.edit"
    )
    for ext in ("json", "html"):
        assert (
            rbac.route_entry("GET", f"/v1/systems/{{system_id}}/regulator-pack.{ext}")
            == "systems.view"
        )


# ------------------------------------------------------------------ the mapping


def test_mapped_controls_leave_out_process_and_none(l4: Console) -> None:
    ob = kb(l4).get(OB_GATE2)
    assert [(k, i) for k, i, _ in de.mapped_controls(ob)] == [
        ("catalogue", "approved_tools"),
        ("catalogue", "single_limit"),
    ]
    # an obligation with only bank processes has no Supervisor control at all
    only_process = [
        o for o in kb(l4).obligations.values() if o.control_mapping and not de.mapped_controls(o)
    ]
    assert only_process, "the KB has duties that only a bank process covers"
    assert de.counter_of("rule", "PII-02") == "rule"
    assert de.counter_of("console", "cases") == "unmeasured"
    assert de.counter_of("monitor", "quality") == "unmeasured"  # an advisory LLM scorer (R1)
    assert de.counter_of("catalogue", "tier1_monitor") == "judge"


# ------------------------------------------------------------------ counts per control


def test_counts_per_control_from_synthetic_rows(l4: Console) -> None:
    sid = system_with_agent(l4)
    gate_events(l4, 3)  # in the window
    gate_events(l4, 2, days=40)  # older than the window
    gate_events(l4, 4, agent="somebody-else")  # another agent
    c = _counts(l4, sid, OB_GATE2)
    assert c == {"approved_tools": 3, "single_limit": 3}
    assert all(type(v) is int for v in c.values())
    # a rule: only the hits the gate enforced count (not a shadow row, not a mock row)
    verdicts(l4, 2)
    verdicts(l4, 1, label="shadow_would")
    verdicts(l4, 1, mock=True)
    verdicts(l4, 1, rule="PAY-01")
    assert _counts(l4, sid, OB_RULE) == {"PII-02": 2}
    # a judge: counted and shown, but advisory
    verdicts(l4, 5, rule=None, tier=1, action="log", label="ok")
    found = de.system_evidence(env(l4), sid, [{"obligation_id": OB_JUDGE}])[OB_JUDGE]
    assert [(x["id"], x["n"], x["advisory"], x["works"]) for x in found["controls"]] == [
        ("tier1_monitor", 5, True, False)
    ]


def test_chain_counters(l4: Console) -> None:
    sid = system_with_agent(l4)
    chain = l4.ctx.runtime.chain
    chain.record("probe", "probe:1", {"agent_id": AGENT, "n": 1})
    chain.record("probe", "probe:2", {"agent_id": AGENT, "n": 2})
    now = l4.ctx.clock.now()  # the chain stamps entries with now: read a window that includes it
    w = ev.Window(now - dt.timedelta(days=1), now + dt.timedelta(hours=1))
    reader = de.reader_for(env(l4), sid, w)
    by = {x["id"]: x for x in de.control_rows(reader, kb(l4).get(OB_CHAIN), 1)}
    assert by["evidence_chain"]["n"] == 2 and by["evidence_chain"]["works"] is True
    assert by["anchor"]["n"] == 0 and by["anchor"]["works"] is False
    assert reader.count("chain_verify") == 0
    chain.record("chain_verify", "chain_verify:1", {"ok": True, "failures": 0, "scope": "all"})
    assert reader.count("chain_verify") == 0  # memoised: the reader asks each question once
    assert de.reader_for(env(l4), sid, w).count("chain_verify") == 1


def test_works_threshold_is_a_setting(l4: Console, monkeypatch: pytest.MonkeyPatch) -> None:
    sid = system_with_agent(l4)
    gate_events(l4, 1)
    one = de.system_evidence(env(l4), sid, [{"obligation_id": OB_MASK}])[OB_MASK]
    assert one["all_work"] is True  # default: one row is enough
    monkeypatch.setattr(l4.ctx.settings, "duty_evidence_min_rows", 2)
    two = de.system_evidence(env(l4), sid, [{"obligation_id": OB_MASK}])[OB_MASK]
    assert two["all_work"] is False and two["controls"][0]["n"] == 1
    gate_events(l4, 1)
    again = de.system_evidence(env(l4), sid, [{"obligation_id": OB_MASK}])[OB_MASK]
    assert again["all_work"] is True


def test_window_setting_and_unsupervised_agent(l4: Console, monkeypatch: Any) -> None:
    sid = system_with_agent(l4)
    gate_events(l4, 2, days=10)
    assert _counts(l4, sid, OB_MASK) == {"pii_masking": 2}
    monkeypatch.setattr(l4.ctx.settings, "duty_evidence_window_days", 7)
    assert _counts(l4, sid, OB_MASK) == {"pii_masking": 0}
    # an agent that is not supervised (SHADOW) is not evidence
    sid2 = system_with_agent(l4, agent="shadow-agent", gate="SHADOW", name="Shadow system")
    gate_events(l4, 3, agent="shadow-agent")
    monkeypatch.setattr(l4.ctx.settings, "duty_evidence_window_days", 30)
    assert _counts(l4, sid2, OB_MASK) == {"pii_masking": 0}


def test_console_screens_and_judges_never_work(l4: Console) -> None:
    sid = system_with_agent(l4)
    gate_events(l4, 3)
    verdicts(l4, 3, rule=None, tier=2, action="log", label="ok")
    found = de.system_evidence(
        env(l4), sid, [{"obligation_id": OB_CONSOLE}, {"obligation_id": OB_MIXED}]
    )
    assert found[OB_CONSOLE]["all_work"] is False
    assert found[OB_CONSOLE]["controls"][0]["measured"] is False
    assert found[OB_MIXED]["all_work"] is False  # tier1_monitor is advisory


# ------------------------------------------------------------------ rule (a): auto-close


def test_refresh_closes_full_rows_when_all_controls_work(l4: Console) -> None:
    sid = system_with_agent(l4)
    gate_events(l4, 4)
    put_row(l4, sid, OB_GATE2)
    system = l4.ctx.systems.get(sid)
    out = de.refresh(env(l4), system)
    assert (out["checked"], out["closed"], out["ids"]) == (1, 1, [OB_GATE2])
    r = row(l4, sid, OB_GATE2)
    assert r["status"] == "closed"
    assert r["closing_control"] == "approved_tools,single_limit"
    assert r["note"].startswith(BANNER + " closed by evidence ")
    assert "approved_tools=4,single_limit=4" in r["note"]
    assert de.close_basis(r) == "evidence"
    assert de.split_note(r["note"]).startswith("closed by evidence ")
    # one chain record, ids and integers
    recs = [
        x for x in l4.ctx.tables.query("chain_entry") if x["record_type"] == "duty_evidence_close"
    ]
    assert len(recs) == 1


def test_refresh_does_not_close_when_a_control_has_no_evidence(l4: Console) -> None:
    sid = system_with_agent(l4)
    gate_events(l4, 4)
    put_row(l4, sid, OB_CHAIN)  # anchor has no row
    put_row(l4, sid, OB_MIXED)  # tier1_monitor is advisory
    put_row(l4, sid, OB_CONSOLE)  # a console screen is unmeasured
    out = de.refresh(env(l4), l4.ctx.systems.get(sid))
    assert out["checked"] == 3 and out["closed"] == 0
    for oid in (OB_CHAIN, OB_MIXED, OB_CONSOLE):
        assert row(l4, sid, oid)["status"] == "open"


def test_refresh_never_closes_partial_none_waived_or_unknown(l4: Console) -> None:
    sid = system_with_agent(l4)
    gate_events(l4, 4)
    ids = sorted({OB_GATE2, OB_MASK, "VN-CPL-2023-A18-01", "VN-DEC117-2018-A11.1-01"})
    put_row(l4, sid, ids[0], coverage="partial")
    put_row(l4, sid, ids[1], coverage="none")
    put_row(l4, sid, ids[2], coverage="full", status="waived")
    put_row(l4, sid, ids[3], coverage="unknown", applies="needs_answer")
    out = de.refresh(env(l4), l4.ctx.systems.get(sid))
    assert out["checked"] == 0 and out["closed"] == 0
    assert [row(l4, sid, o)["status"] for o in ids] == ["open", "open", "waived", "open"]


def test_refresh_is_idempotent(l4: Console) -> None:
    sid = system_with_agent(l4)
    gate_events(l4, 2)
    put_row(l4, sid, OB_MASK)
    system = l4.ctx.systems.get(sid)
    first = de.refresh(env(l4), system)
    version = row(l4, sid, OB_MASK)["row_version"]
    second = de.refresh(env(l4), system)
    assert first["closed"] == 1 and second == {"checked": 0, "closed": 0, "conflicts": 0, "ids": []}
    assert row(l4, sid, OB_MASK)["row_version"] == version


def test_a_person_close_keeps_the_typed_evidence_after_the_banner(l4: Console) -> None:
    sid = system_with_agent(l4)
    cid = _control(l4)
    oid = _ids(l4, "VN-DEC142-2026", 1)[0]
    put_row(l4, sid, oid, coverage="partial")
    r = l4.post(
        _url(sid, "close"),
        {
            "status_id": row(l4, sid, oid)["status_id"],
            "closing_control": cid,
            "evidence_ref": EVIDENCE,
        },
        user=CREATOR,
    )
    assert r.status_code == 200, r.text[:300]
    stored = row(l4, sid, oid)
    assert stored["closing_control"] == cid
    assert de.close_basis(stored) == "person"
    assert EVIDENCE in de.split_note(stored["note"])
    assert not de.split_note(stored["note"]).startswith(BANNER)


# ------------------------------------------------------------------ rule (b): the group task


def _two_partial(c: Console, sid: str) -> tuple[str, list[str], str]:
    ids = _ids(c, "VN-DEC142-2026", 2)
    for oid in ids:
        put_row(c, sid, oid, coverage="partial")
    inst = kb(c).get(ids[0]).instrument_id
    return inst, ids, gap_task(c, sid, inst, "partial")


def _close(c: Console, sid: str, oid: str, cid: str) -> Any:
    r = c.post(
        _url(sid, "close"),
        {
            "status_id": row(c, sid, oid)["status_id"],
            "closing_control": cid,
            "evidence_ref": EVIDENCE,
        },
        user=CREATOR,
    )
    assert r.status_code == 200, r.text[:300]
    return r


def _task(c: Console, tid: str) -> dict[str, Any]:
    t = c.ctx.state.get("task", {"task_id": tid})
    assert t is not None
    return dict(t)


def test_group_task_closes_when_the_last_row_closes(l4: Console) -> None:
    sid = system_with_agent(l4)
    cid = _control(l4)
    inst, ids, tid = _two_partial(l4, sid)
    _close(l4, sid, ids[0], cid)
    assert _task(l4, tid)["status"] == "open"  # one row is still open
    _close(l4, sid, ids[1], cid)
    t = _task(l4, tid)
    assert t["status"] == "done" and t["done_by"] == de.TASK_ACTOR
    assert "all duties of the group closed" in t["evidence_ref"]
    events = [
        e for e in l4.ctx.tables.query("task_event", {"task_id": tid}) if e["action"] == "done"
    ]
    assert len(events) == 1


def test_group_task_closes_with_a_waived_sibling(l4: Console) -> None:
    sid = system_with_agent(l4)
    cid = _control(l4)
    inst, ids, tid = _two_partial(l4, sid)
    r = l4.post(
        _url(sid, "waive"),
        {
            "status_id": row(l4, sid, ids[0])["status_id"],
            "reason": "The vendor report covers this duty.",
        },
        user="approver.em",
    )
    assert r.status_code == 200, r.text[:300]
    assert _task(l4, tid)["status"] == "open"
    _close(l4, sid, ids[1], cid)
    assert _task(l4, tid)["status"] == "done"


def test_group_task_stays_open_with_the_flag_off(
    l4: Console, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(l4.ctx.settings, "regulator_pack", False)
    sid = system_with_agent(l4)
    cid = _control(l4)
    inst, ids, tid = _two_partial(l4, sid)
    _close(l4, sid, ids[0], cid)
    _close(l4, sid, ids[1], cid)
    assert _task(l4, tid)["status"] == "open"  # as before WP-L4


def test_other_groups_are_not_touched(l4: Console) -> None:
    sid = system_with_agent(l4)
    cid = _control(l4)
    inst, ids, tid = _two_partial(l4, sid)
    other = gap_task(l4, sid, inst, "none")
    _close(l4, sid, ids[0], cid)
    _close(l4, sid, ids[1], cid)
    assert _task(l4, tid)["status"] == "done" and _task(l4, other)["status"] == "open"


# ------------------------------------------------------------------ the sweep


def _job_env(c: Console) -> de.Env:
    from supervisor.monitors.common import MonitorContext

    mctx = MonitorContext.from_adapters(c.runtime.adapters, c.runtime.chain)
    return de.Env.from_job(mctx, c.ctx.settings)


def test_sweep_closes_for_every_system_and_is_idempotent(l4: Console) -> None:
    a = system_with_agent(l4)
    b = system_with_agent(l4, agent="l4-agent-b", name="Second system")
    gate_events(l4, 3)
    gate_events(l4, 3, agent="l4-agent-b")
    put_row(l4, a, OB_MASK)
    put_row(l4, b, OB_MASK)
    put_row(l4, b, OB_CHAIN)  # stays open: anchor has no row
    out = de.sweep(_job_env(l4))
    assert out == {"systems": 2, "checked": 3, "closed": 2, "conflicts": 0}
    assert de.sweep(_job_env(l4)) == {"systems": 1, "checked": 1, "closed": 0, "conflicts": 0}
    assert row(l4, a, OB_MASK)["status"] == "closed" and row(l4, b, OB_CHAIN)["status"] == "open"
    rows = [r for r in _audit(l4) if r["path"] == "/jobs/duty_evidence_sweep"]
    assert len(rows) == 2 and {r["actor"] for r in rows} == {"system"}
    assert {r["actor_kind"] for r in rows} == {"system"} and all(r["outcome"] == "ok" for r in rows)
    assert all(r["before_hash"] != r["after_hash"] for r in rows)


def test_sweep_job_gating(l4: Console, monkeypatch: pytest.MonkeyPatch) -> None:
    from supervisor.jobs import duty_evidence_sweep as job

    s = l4.ctx.settings
    assert job.enabled(s) is False  # DUTY_EVIDENCE_SWEEP_S is 0
    monkeypatch.setattr(s, "duty_evidence_sweep_s", 300)
    assert job.enabled(s) is True
    monkeypatch.setattr(s, "regulator_pack", False)
    assert job.enabled(s) is False
    monkeypatch.setattr(s, "regulator_pack", True)
    sid = system_with_agent(l4)
    gate_events(l4, 1)
    put_row(l4, sid, OB_MASK)
    from supervisor.monitors.common import MonitorContext

    mctx = MonitorContext.from_adapters(l4.runtime.adapters, l4.runtime.chain)
    assert job.run(mctx, s)["closed"] == 1


def test_archived_system_is_skipped(l4: Console) -> None:
    sid = system_with_agent(l4)
    gate_events(l4, 1)
    put_row(l4, sid, OB_MASK)
    l4.ctx.state.update(
        "ai_system",
        {"system_id": sid},
        {"status": "archived"},
        int(l4.ctx.state.get("ai_system", {"system_id": sid})["row_version"]),
    )
    assert de.sweep(_job_env(l4))["systems"] == 0


# ------------------------------------------------------------------ the button


def test_refresh_button_closes_and_writes_two_audit_rows(l4: Console) -> None:
    sid = system_with_agent(l4)
    gate_events(l4, 2)
    put_row(l4, sid, OB_MASK)
    n0 = len(_audit(l4))
    r = l4.post(_url(sid, "refresh-evidence"), {}, user=CREATOR)
    assert r.status_code == 200, r.text[:300]
    assert row(l4, sid, OB_MASK)["status"] == "closed"
    new = _audit(l4)[n0:]
    assert [x["outcome"] for x in new] == ["attempted", "ok"]
    assert {x["permission"] for x in new} == {"systems.edit"} and new[1]["actor"] == CREATOR
    assert new[1]["detail"] == "duty_evidence_refresh checked=1 closed=1"
    assert new[1]["before_hash"] != new[1]["after_hash"]
    assert "Evidence read again" in r.text
    again = l4.post(_url(sid, "refresh-evidence"), {}, user=CREATOR)
    assert again.status_code == 200 and "closed=0" in _audit(l4)[-1]["detail"]


def test_refresh_button_roles(l4: Console) -> None:
    sid = system_with_agent(l4)
    put_row(l4, sid, OB_MASK)
    for user in ("viewer.hoa", "auditor.dung"):
        assert l4.post(_url(sid, "refresh-evidence"), {}, user=user).status_code == 403
    assert row(l4, sid, OB_MASK)["status"] == "open"
    assert l4.post(_url("sys_nope", "refresh-evidence"), {}, user=CREATOR).status_code == 400


def test_flag_off_refresh_is_400_and_the_tab_is_as_before(
    l4: Console, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(l4.ctx.settings, "regulator_pack", False)
    sid = system_with_agent(l4)
    gate_events(l4, 2)
    put_row(l4, sid, OB_MASK)
    r = l4.post(_url(sid, "refresh-evidence"), {}, user=CREATOR)
    assert r.status_code == 400 and "regulator_pack_off" in r.text and "REGULATOR_PACK" in r.text
    assert row(l4, sid, OB_MASK)["status"] == "open"
    html = _tab(l4, sid, "&f=all").text
    for marker in ('data-du="evidence"', "refresh-evidence", "regulator-pack"):
        assert marker not in html
    head = l4.get(f"/console/systems/{sid}?lang=en").text
    assert "regulator-pack" not in head


# ------------------------------------------------------------------ the tab


def test_tab_shows_counts_marks_and_close_evidence(l4: Console) -> None:
    sid = system_with_agent(l4)
    gate_events(l4, 3)
    put_row(l4, sid, OB_MASK)  # works
    put_row(l4, sid, OB_CHAIN)  # no evidence
    put_row(l4, sid, OB_JUDGE, coverage="partial")  # advisory
    html = _tab(l4, sid, "&f=all").text
    assert 'data-du="evidence"' in html
    assert 'data-control="pii_masking"' in html and "pii_masking=3" in html
    assert "anchor=0" in html and "evidence_chain=0" in html
    assert "tier1_monitor=0" in html and "advisory" in html
    assert "works" in html and "no evidence" in html
    assert f"/v1/systems/{sid}/regulator-pack.html" in html
    assert f"/v1/systems/{sid}/regulator-pack.json" in html
    assert 'data-act="duty-refresh-evidence"' in html
    # after the system closes the row, the tab shows how (note after the banner) and the control
    de.refresh(env(l4), l4.ctx.systems.get(sid))
    closed = _tab(l4, sid, "&f=closed").text
    assert "pii_masking" in closed and "closed by evidence" in closed
    assert BANNER not in closed.split('data-du="detail"', 1)[1].split("</div>", 1)[0]


def test_tab_hides_the_refresh_button_from_a_reader(l4: Console) -> None:
    sid = system_with_agent(l4)
    put_row(l4, sid, OB_MASK)
    html = l4.get(f"/console/systems/{sid}?tab=duties&lang=en&f=all", user="auditor.dung").text
    assert 'data-du="evidence"' in html
    assert 'data-act="duty-refresh-evidence"' not in html
    assert 'data-act="regulator-pack-html"' in html


def test_time_helpers_are_consistent(l4: Console) -> None:
    w = env(l4).window()
    assert w.end <= l4.ctx.clock.now() and (w.end - w.start) == dt.timedelta(days=30)
    assert when(l4) < l4.ctx.clock.now()
    assert person  # the shared fixture helper is importable

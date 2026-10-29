"""WP-W2: the governance event ``regkb_changed`` and its rules (config/governance_actions.yaml).

An applied law change (a ``regkb_change`` row) becomes one event per system. The shipped rules
re-open the duty rows mapped to the changed articles, make the gap tasks, send the owner notice,
fire the outbound event, and move a deployed system to re-evaluation only when a classification
article changed or a full or partial duty on the classification path is affected. The rows are
written straight into the tables; the runner is the real one with the shipped rules file.
"""

from __future__ import annotations

import datetime as dt
import json
from pathlib import Path
from typing import Any

import pytest

from supervisor.governance import event_sources as src
from supervisor.governance import regkb_reopen
from supervisor.governance.actions_model import ACTION_KINDS, EVENT_KINDS, load_rules
from supervisor.governance.register_v2 import duties as dut
from supervisor.regkb import change

from .g5_support import NOW, STARTER, Rig, ago

SOURCES = {"regkb_changes": src.regkb_changes}
IID = "VN-DEC142-2026"
NON_PATH = f"{IID}-A5.03-01"  # Art. 5(3): not cited by the classification tree
ON_PATH = f"{IID}-A9.01-01"  # Art. 9(1): cited by the classification tree
SHA = "ab12cd34" + "0" * 56


@pytest.fixture
def w2(rig: Rig, monkeypatch: pytest.MonkeyPatch) -> Rig:
    monkeypatch.setattr(rig.a.settings, "regkb_change_loop", True)
    monkeypatch.setenv("DATA_DIR", str(rig.a.settings.data_dir))
    monkeypatch.setenv("REGKB_CHANGE_LOOP", "1")
    return rig


def deployed(rig: Rig, name: str, stage: str = "deployment") -> str:
    s = rig.system(name, agent=None)
    sid = str(s["system_id"])
    rig.stage(sid, stage)
    return sid


def duty(
    rig: Rig, sid: str, oid: str, *, coverage: str = "partial", status: str = "closed"
) -> None:
    rig.a.state.insert(
        "obligation_status",
        {
            "status_id": dut.status_id(sid, oid),
            "system_id": sid,
            "obligation_id": oid,
            "instrument_id": IID,
            "applies": "yes",
            "coverage": coverage,
            "status": status,
            "owner_user": "owner.lan",
            "due_date": None,
            "closing_control": "CTL-X" if status == "closed" else None,
            "note": "earlier note",
            "created_at": ago(86400),
        },
    )


def applied_change(
    rig: Rig,
    affected: list[str],
    *,
    hit: bool = False,
    sha: str = SHA,
    when: dt.datetime | None = None,
    status: str = "applied",
) -> str:
    cid = change.change_id_of(sha, IID)
    rig.a.state.insert(
        "regkb_change",
        {
            "change_id": cid,
            "package_sha": sha,
            "instrument_id": IID,
            "status": status,
            "old_sha": "1" * 64,
            "new_sha": "2" * 64,
            "incoming_name": f"{IID}/2026-10-21/x.txt",
            "articles_changed": 1,
            "articles_added": 0,
            "articles_removed": 0,
            "changed_chars": 12,
            "articles": [5],
            "obligations_affected": affected,
            "classification_hit": hit,
            "drafts_n": 0,
            "model_id": None,
            "obligations_added": 0,
            "obligations_updated": 0,
            "obligations_removed": 0,
            "created_at": ago(3600),
            "created_by": "approver.hoa",
            "applied_at": (when or ago(60)) if status == "applied" else None,
            "applied_by": "approver.hoa" if status == "applied" else None,
        },
    )
    return cid


def run(rig: Rig) -> Any:
    return rig.runner(load_rules(STARTER), sources=SOURCES).run()


def row(rig: Rig, sid: str, oid: str) -> dict[str, Any]:
    r = rig.a.state.get("obligation_status", {"status_id": dut.status_id(sid, oid)})
    assert r is not None
    return dict(r)


def stage_of(rig: Rig, sid: str) -> str:
    r = rig.a.state.get("ai_system", {"system_id": sid})
    assert r is not None
    return str(r["lifecycle_stage"])


# ------------------------------------------------------------------------------ vocabulary


def test_the_event_kind_the_action_and_the_shipped_rules() -> None:
    assert "regkb_changed" in EVENT_KINDS and "reopen_obligations" in ACTION_KINDS
    rules = {r.id: r for r in load_rules(STARTER)}
    a = rules["GA-REGKB-CHANGED"]
    assert (a.kind, a.min_severity) == ("regkb_changed", "medium")
    assert a.actions == ("reopen_obligations", "notify_owner", "fire_webhook")
    b = rules["GA-REGKB-CHANGED-CLASSIFICATION"]
    assert (b.kind, b.min_severity, b.actions) == (
        "regkb_changed",
        "high",
        ("move_to_re_evaluation",),
    )
    assert "regkb_changes" in src.SOURCES


# ------------------------------------------------------------------------------ off path


def test_off_path_no_event_without_an_applied_change(w2: Rig) -> None:
    deployed(w2, "Alpha")
    res = run(w2)
    assert res.events == 0 and res.handled == 0
    assert w2.a.state.query("governance_event") == []
    # a diffed change that was never applied is not an event either
    applied_change(w2, [NON_PATH], status="diffed")
    assert run(w2).events == 0


def test_the_action_does_nothing_while_the_flag_is_off(
    w2: Rig, monkeypatch: pytest.MonkeyPatch
) -> None:
    sid = deployed(w2, "Alpha")
    duty(w2, sid, NON_PATH)
    applied_change(w2, [NON_PATH])
    monkeypatch.setattr(w2.a.settings, "regkb_change_loop", False)
    run(w2)
    (m,) = w2.a.state.query("governance_event")
    got = {a["action"]: (a["status"], a["ref"]) for a in m["actions"]}
    assert got["reopen_obligations"] == ("skipped", "change_loop_off")
    assert row(w2, sid, NON_PATH)["status"] == "closed"
    assert w2.a.state.query("task") == []


# ------------------------------------------------------------------------------ reopen, tasks


def test_rows_are_reopened_with_the_note_and_the_gap_task_is_made(w2: Rig) -> None:
    a = deployed(w2, "Alpha")
    b = deployed(w2, "Beta")
    other = deployed(w2, "Gamma")  # no row for the changed obligation: no event
    duty(w2, a, NON_PATH, coverage="partial", status="closed")
    duty(w2, b, NON_PATH, coverage="none", status="waived")
    duty(w2, other, ON_PATH, status="closed")  # an obligation that did not change
    applied_change(w2, [NON_PATH])
    res = run(w2)
    assert res.events == 2 and res.handled == 2 and res.failed == 0, res
    for sid in (a, b):
        r = row(w2, sid, NON_PATH)
        assert r["status"] == "open" and r["closing_control"] is None
        assert "article changed on 2026-10-22 (package ab12cd34)" in r["note"]
        assert "earlier note" in r["note"]  # the old note is kept after the new one
    assert row(w2, other, ON_PATH)["status"] == "closed"
    # one gap task per system and group, with the WP-L3 text
    tasks = {t["agent_id"]: dict(t) for t in w2.a.state.query("task")}
    assert set(tasks) == {a, b}
    assert (
        tasks[a]["title"].startswith("Close 1 duty of ")
        and "(coverage partial)" in tasks[a]["title"]
    )
    assert "(coverage none)" in tasks[b]["title"]
    assert all(t["template_id"].startswith("DUTY-CHG-ab12cd34-") for t in tasks.values())
    assert NON_PATH in tasks[a]["evidence_ref"]
    # a medium event: no move to re-evaluation
    assert stage_of(w2, a) == "deployment" and stage_of(w2, b) == "deployment"
    # the owner notice and the outbound event
    notices = w2.a.state.query("notice")
    assert len(notices) == 2 and all(n["channel"] == "owner:owner.lan" for n in notices)
    assert len(w2.a.state.query("outbound_event", {"kind": "governance_action"})) == 2
    # the chain record: integers and ids only
    records = w2.sink.of("regkb_reopen")
    assert len(records) == 2
    for p in records:
        assert p["reopened_n"] == 1 and p["rows_n"] == 1 and p["tasks_n"] == 1
        for k, v in p.items():
            assert isinstance(v, (str, int)) and not isinstance(v, (bool, float)), k
    # the marker says what each action did
    by_sys = {
        m["system_id"]: {x["action"]: x["status"] for x in m["actions"]}
        for m in w2.a.state.query("governance_event")
    }
    assert by_sys[a] == {
        "reopen_obligations": "done",
        "notify_owner": "done",
        "fire_webhook": "done",
    }


def test_an_open_row_only_gets_the_note_and_a_repeat_changes_nothing(w2: Rig) -> None:
    sid = deployed(w2, "Alpha")
    duty(w2, sid, NON_PATH, status="open")
    applied_change(w2, [NON_PATH])
    run(w2)
    r = row(w2, sid, NON_PATH)
    assert r["status"] == "open" and "article changed on 2026-10-22" in r["note"]
    (rec,) = w2.sink.of("regkb_reopen")
    assert rec["rows_n"] == 1 and rec["reopened_n"] == 0 and rec["tasks_n"] == 0
    assert w2.a.state.query("task") == []
    # a second run: the marker stops it
    again = run(w2)
    assert again.handled == 0 and again.already == 1
    assert len(w2.sink.of("regkb_reopen")) == 1


def test_a_needs_answer_row_is_not_reopened(w2: Rig) -> None:
    sid = deployed(w2, "Alpha")
    duty(w2, sid, NON_PATH, status="open")
    r = row(w2, sid, NON_PATH)
    w2.a.state.update(
        "obligation_status",
        {"status_id": r["status_id"]},
        {"applies": "needs_answer", "coverage": "unknown"},
        int(r["row_version"]),
    )
    applied_change(w2, [NON_PATH])
    run(w2)
    assert row(w2, sid, NON_PATH)["status"] == "open"
    assert w2.a.state.query("task") == []


def test_the_reopen_counts_helper_is_deterministic(w2: Rig) -> None:
    sid = deployed(w2, "Alpha")
    duty(w2, sid, NON_PATH)
    cid = applied_change(w2, [NON_PATH])
    ctx = w2.ctx
    status, counts = regkb_reopen.reopen(ctx, w2.a.settings, sid, cid, "system:test")
    assert status == "done" and counts == {"rows_n": 1, "reopened_n": 1, "tasks_n": 1}
    status, counts = regkb_reopen.reopen(ctx, w2.a.settings, sid, cid, "system:test")
    assert status == "done" and counts["reopened_n"] == 0 and counts["tasks_n"] == 0
    assert regkb_reopen.reopen(ctx, w2.a.settings, sid, "rc_missing", "system:test")[0] == "skipped"


# ------------------------------------------------------------------------------ re-evaluation


def test_a_classification_article_moves_deployed_systems_to_re_evaluation(w2: Rig) -> None:
    dep = deployed(w2, "Alpha", "deployment")
    op = deployed(w2, "Beta", "operation")
    early = deployed(w2, "Gamma", "initiation")
    applied_change(w2, [], hit=True)  # no duty row at all: the change touches the classification
    res = run(w2)
    assert res.events == 3 and res.failed == 0, res
    assert stage_of(w2, dep) == "re_evaluation" and stage_of(w2, op) == "re_evaluation"
    assert stage_of(w2, early) == "initiation"  # not deployed: skipped, never forced
    by_sys = {
        m["system_id"]: {x["action"]: x["status"] for x in m["actions"]}
        for m in w2.a.state.query("governance_event")
    }
    assert by_sys[dep]["move_to_re_evaluation"] == "done"
    assert by_sys[early]["move_to_re_evaluation"] == "skipped"
    assert all(m["severity"] == "high" for m in w2.a.state.query("governance_event"))
    moves = [p for p in w2.sink.of("stage_change") if p["action"] == "move"]
    assert sorted(p["to_stage"] for p in moves) == ["re_evaluation", "re_evaluation"]


def test_a_full_or_partial_duty_on_the_classification_path_moves_the_system(w2: Rig) -> None:
    partial = deployed(w2, "Alpha")
    full = deployed(w2, "Beta")
    none_ = deployed(w2, "Gamma")
    off_path = deployed(w2, "Delta")
    duty(w2, partial, ON_PATH, coverage="partial")
    duty(w2, full, ON_PATH, coverage="full")
    duty(w2, none_, ON_PATH, coverage="none")
    duty(w2, off_path, NON_PATH, coverage="full")  # full, but not on the path
    applied_change(w2, [ON_PATH, NON_PATH], hit=False)
    run(w2)
    assert stage_of(w2, partial) == "re_evaluation" and stage_of(w2, full) == "re_evaluation"
    assert stage_of(w2, none_) == "deployment" and stage_of(w2, off_path) == "deployment"
    sev = {m["system_id"]: m["severity"] for m in w2.a.state.query("governance_event")}
    assert sev == {partial: "high", full: "high", none_: "medium", off_path: "medium"}
    # the duty rows are open again for all four, whatever the stage
    assert all(
        row(w2, s, o)["status"] == "open"
        for s, o in ((partial, ON_PATH), (full, ON_PATH), (none_, ON_PATH), (off_path, NON_PATH))
    )


def test_an_archived_system_gets_no_event(w2: Rig) -> None:
    sid = deployed(w2, "Alpha")
    duty(w2, sid, NON_PATH)
    r = w2.a.state.get("ai_system", {"system_id": sid})
    assert r is not None
    w2.a.state.update(
        "ai_system", {"system_id": sid}, {"status": "archived"}, int(r["row_version"])
    )
    applied_change(w2, [NON_PATH], hit=True)
    assert run(w2).events == 0


# ------------------------------------------------------------------------------ the banner


def write_package(rig: Rig, sha: str = SHA) -> None:
    base = Path(rig.a.settings.data_dir) / "regkb" / "incoming" / sha
    base.mkdir(parents=True)
    (base / "import.json").write_text(
        json.dumps(
            {"package_sha256": sha, "run_id": "rw_1", "imported_at": "2026-10-20T10:00:00Z"}
        ),
        encoding="utf-8",
    )
    (base / "watch-2026-10-20.json").write_text(
        json.dumps(
            {
                "summary": {"changes_found": 1},
                "instruments": [
                    {
                        "instrument_id": IID,
                        "changes": [
                            {
                                "kind": "text_changed",
                                "instrument_id": IID,
                                "incoming": [f"{IID}/2026-10-20/x.txt"],
                            }
                        ],
                    }
                ],
            }
        ),
        encoding="utf-8",
    )


def test_banner_states(w2: Rig) -> None:
    data_dir = w2.a.settings.data_dir
    state = w2.a.state
    assert change.banner(state, data_dir, NOW) is None  # nothing imported
    write_package(w2)
    assert change.banner(state, data_dir, NOW) == {"pending": 1, "applied": []}
    # diffed: still pending review
    applied_change(w2, [NON_PATH], status="diffed")
    assert change.banner(state, data_dir, NOW) == {"pending": 1, "applied": []}


def test_banner_after_apply_counts_the_reopened_systems_for_seven_days(w2: Rig) -> None:
    data_dir = w2.a.settings.data_dir
    write_package(w2)
    a = deployed(w2, "Alpha")
    b = deployed(w2, "Beta")
    duty(w2, a, NON_PATH)
    duty(w2, b, NON_PATH)
    applied_change(w2, [NON_PATH])
    run(w2)
    got = change.banner(w2.a.state, data_dir, NOW)
    assert got is not None and got["pending"] == 0
    (line,) = got["applied"]
    assert line["date"] == "2026-10-22" and line["systems"] == 2 and line["instrument_id"] == IID
    day6 = NOW + dt.timedelta(days=6)
    assert change.banner(w2.a.state, data_dir, day6) is not None
    day8 = NOW + dt.timedelta(days=8)
    assert change.banner(w2.a.state, data_dir, day8) is None

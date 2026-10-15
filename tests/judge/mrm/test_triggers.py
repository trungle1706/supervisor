"""WP19: re-validation triggers."""

from __future__ import annotations

import json
from datetime import timedelta
from typing import Any

from supervisor.config import load_settings
from supervisor.judge.mrm import control
from supervisor.judge.mrm.control import current_identity, fired_triggers
from supervisor.judge.router import JudgeRouter
from tests.judge.conftest import T0, MemoryTables

S = load_settings(judge_t2_sample_bp=0)
ROUTER = JudgeRouter.from_settings(S)
IDENT = current_identity(ROUTER, S)
NOW = T0 + timedelta(days=30)


def val(**over: Any) -> dict[str, Any]:
    row = {
        "validation_id": "mv-1",
        "ts": T0,
        "model_version": IDENT.model_version,
        "prompt_hash": IDENT.prompt_hash,
        "rubric_version": IDENT.rubric_version,
        "golden_set_hash": IDENT.golden_set_hash,
        "decision": "GO",
        "passed": True,
    }
    row.update(over)
    return row


def agent(aid: str, created, tier="high", cls="decision33") -> dict[str, Any]:
    return {"agent_id": aid, "created_at": created, "risk_tier": tier, "decision33_class": cls}


def metric(day: str, pairs: int, bp: int) -> dict[str, Any]:
    return {
        "metric_date": day,
        "agent_id": "a1",
        "judge_human_pairs": pairs,
        "judge_human_agree_bp": bp,
    }


def run(t: MemoryTables) -> dict[str, dict[str, Any]]:
    res = fired_triggers(S, t, router=ROUTER, now=NOW)
    return {x["id"]: x for x in res["triggers"]}


def fired(t: MemoryTables) -> set[str]:
    return {k for k, v in run(t).items() if v["fired"]}


def base() -> MemoryTables:
    t = MemoryTables()
    t.append("model_validation", [val()])
    t.append("agent", [agent("a1", T0 - timedelta(days=5))])
    return t


def test_never_validated() -> None:
    res = run(MemoryTables())
    assert list(res) == ["never_validated"] and res["never_validated"]["fired"]


def test_nothing_fired() -> None:
    assert fired(base()) == set()


def test_any_decision_counts_as_last_validation() -> None:
    t = base()
    t.append(
        "model_validation",
        [val(validation_id="2", ts=T0 + timedelta(days=1), decision="NO_GO", passed=False)],
    )
    assert fired(t) == set()


def test_each_identity_trigger() -> None:
    for field, trig in (
        ("prompt_hash", "prompt_changed"),
        ("model_version", "model_version_changed"),
        ("rubric_version", "rubric_changed"),
        ("golden_set_hash", "golden_set_changed"),
    ):
        t = MemoryTables()
        t.append("model_validation", [val(**{field: "different"})])
        assert fired(t) == {trig}, trig


def test_agreement_daily_row() -> None:
    t = base()
    t.append("oversight_metric", [metric("2026-10-20", 4, 1000), metric("2026-10-21", 10, 9000)])
    assert fired(t) == set()  # too few pairs / above threshold
    t.append("oversight_metric", [metric("2026-10-22", 5, 7999)])
    assert fired(t) == {"agreement_below_threshold"}


def test_agreement_period() -> None:
    t = base()
    for i in range(6):
        t.append(
            "case_link",
            [{"source_kind": "judge", "source_ref": f"v{i}", "case_id": f"c{i}",
              "agent_id": "a1", "ts": T0}],
        )  # fmt: skip
        decision = "close:false_alarm" if i < 3 else "close:confirmed"
        t.append(
            "signoff",
            [{"signoff_id": f"s{i}", "case_id": f"c{i}", "reviewer_id": "r",
              "decision": decision, "ts": T0 + timedelta(days=2)}],
        )  # fmt: skip
    assert fired(t) == {"agreement_below_threshold"}


def test_new_agent_class() -> None:
    t = base()
    t.append("agent", [agent("a2", T0 + timedelta(days=1))])
    assert fired(t) == set()  # same class as a1
    t.append("agent", [agent("a3", T0 + timedelta(days=2), tier="critical", cls="credit")])
    res = run(t)
    assert res["new_agent_class_onboarded"]["fired"]
    assert "a3" in res["new_agent_class_onboarded"]["detail"]
    assert "a2" not in res["new_agent_class_onboarded"]["detail"]


def test_cli_exit_codes_and_ascii(monkeypatch, capsys, tmp_path) -> None:
    monkeypatch.setenv("DB_PATH", str(tmp_path / "s.db"))
    rc = control.main(["--json"])
    out = capsys.readouterr().out
    assert rc in (1, 2)
    if rc == 2:  # no usable store here: still a clean FAIL line, no traceback
        assert out.startswith("[FAIL]")
        return
    assert json.loads(out)["triggers"][0]["id"] == "never_validated"
    assert control.main([]) == 1
    text = capsys.readouterr().out
    assert "[FIRED] never_validated" in text and text.isascii()


def test_periodic_revalidation_due_after_a_year() -> None:
    late = fired_triggers(S, base(), router=ROUTER, now=T0 + timedelta(days=366))
    ids = {x["id"] for x in late["triggers"] if x["fired"]}
    assert ids == {"periodic_revalidation_due"}

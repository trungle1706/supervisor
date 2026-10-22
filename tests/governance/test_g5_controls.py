"""WP-G5: a reopened control and the evidence pass of the same window (review M2)."""

from __future__ import annotations

from typing import Any

from .g5_support import Rig

EVENT = "k" * 32


def reasons(rig: Rig) -> list[str]:
    rows = rig.a.tables.query("control_status", {"control_id": "CTL-PII"}, order_by=("ts",))
    return [str(r["reason"]) for r in rows]


def setup(rig: Rig) -> None:
    rig.system()
    rig.control("CTL-PII", "pack", "counterfactual_vi")


def item(rig: Rig) -> dict[str, Any]:
    (c,) = rig.controls.agent_compliance("agent-a")["controls"]
    return dict(c)


def test_reopen_before_the_pass_holds_for_the_window(rig: Rig) -> None:
    setup(rig)
    rig.controls.reopen("CTL-PII", "agent-a", EVENT, "system:test")
    rig.a.clock.advance(5)
    out = rig.controls.run_status()
    assert out["held"] == 1 and out["written"] == 0
    assert reasons(rig) == ["reopened_by_event"]  # the pass did not write over it
    assert item(rig)["reason"] == "reopened_by_event" and item(rig)["status"] == "failing"
    again = rig.controls.run_status()
    assert again["written"] == 0 and item(rig)["status"] == "failing"


def test_reopen_after_the_pass_wins_while_it_is_newest(rig: Rig) -> None:
    setup(rig)
    out = rig.controls.run_status()
    assert out["written"] == 1 and reasons(rig) != ["reopened_by_event"]
    rig.a.clock.advance(5)
    rig.controls.reopen("CTL-PII", "agent-a", EVENT, "system:test")
    assert item(rig)["status"] == "failing" and item(rig)["reason"] == "reopened_by_event"
    rig.controls.run_status()  # same window: the old row repeats, the reopen still wins
    assert item(rig)["reason"] == "reopened_by_event"


def test_the_next_window_lets_the_evidence_decide_again(rig: Rig) -> None:
    setup(rig)
    rig.controls.reopen("CTL-PII", "agent-a", EVENT, "system:test")
    rig.a.clock.advance(5)
    rig.controls.run_status()
    assert item(rig)["reason"] == "reopened_by_event"
    rig.a.clock.advance(2 * 3600)  # windows end at the full hour: this is a later window
    out = rig.controls.run_status()
    assert out["written"] == 1 and out.get("held", 0) == 0
    assert item(rig)["reason"] != "reopened_by_event"
    assert reasons(rig)[0] == "reopened_by_event" and len(reasons(rig)) == 2

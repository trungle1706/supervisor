"""WP12: Agents screen - lifecycle stepper derivation, cards, the one relevant action."""

from __future__ import annotations

import re

from supervisor.console.readmodels import STAGES, lifecycle

from .conftest import Console


def _states(steps: list[dict[str, str]]) -> list[str]:
    return [s["state"] for s in steps]


def test_lifecycle_registered_agent_defaults_to_operate() -> None:
    for state in ("RUNNING", "PAUSED", "QUARANTINED"):
        steps = lifecycle(state, set())
        assert _states(steps) == ["done"] * 5 + ["now"]
        assert steps[-1]["note"] == "stage_note_enforced"


def test_lifecycle_shadow_is_launch() -> None:
    steps = lifecycle("SHADOW", {"inventory.json"})
    assert _states(steps) == ["done"] * 4 + ["now", "todo"]
    assert steps[4] == {"key": "launch", "state": "now", "note": "stage_note_shadow"}


def test_lifecycle_from_onboard_artefacts_only() -> None:
    assert _states(lifecycle(None, set())) == ["now"] + ["todo"] * 5
    arts = {"inventory.json", "profile.json", "plan.json"}
    assert _states(lifecycle(None, arts)) == ["done"] * 3 + ["now", "todo", "todo"]
    arts |= {"pr_description.md", "launch_report.json", "handover.json"}
    assert lifecycle(None, arts)[-1]["state"] == "now"
    assert [s["key"] for s in lifecycle(None, arts)] == list(STAGES)


def test_agents_cards_show_state_rule_action(console: Console) -> None:
    # a rule pause (what the gateway does on PAY-07): principal "rule:<id>"
    console.runtime.gateway.states.pause("payments", "rule:PAY-07", "PAY-07 matched")
    # WP-UX2: the card (and its action) moved from the Agents list to the agent page
    r = console.get("/console/agents/payments")
    assert r.status_code == 200, r.text
    # the card says which rule paused it and offers resume, not pause
    card = r.text.split('data-agent="payments"', 1)[1].split("</article>", 1)[0]
    assert 'data-state="PAUSED"' in r.text
    assert "by rule PAY-07" in card
    assert "/console/agents/payments/resume" in card and "/agents/payments/pause" not in card
    assert "Needs the agent owner and a reviewer, two different people." in card
    assert "You are the reviewer." in card
    assert card.count('data-stage-state="done"') == 5 and 'data-stage="operate"' in card
    assert re.search(r'data-coverage="\d+"', card)
    assert "money-moving" in card and "fail mode closed" in card
    # a running agent offers pause (one click) with the rule under the button
    o = console.get("/console/agents/credit_prequal")
    other = o.text.split('data-agent="credit_prequal"', 1)[1].split("</article>", 1)[0]
    assert "/console/agents/credit_prequal/pause" in other and "Pause now" in other
    assert "One click by any reviewer." in other
    # admin-only quarantine is not offered to a reviewer
    assert "/quarantine" not in r.text and "/quarantine" not in o.text
    admin = console.get("/console/agents/credit_prequal", user="admin.chi")
    assert "/console/agents/credit_prequal/quarantine" in admin.text
    # and the list no longer carries the cards
    assert 'data-agent="payments"' not in console.get("/console/agents").text


def test_coverage_never_counts_planned_capabilities(console: Console) -> None:
    from supervisor.console.readmodels import _coverage

    state = console.ctx.state
    for i, status in enumerate(("planned", "planned", "off")):
        state.insert(
            "coverage",
            {"agent_id": "payments", "capability_id": f"cap{i}", "status": status, "reason": None},
        )
    cov = _coverage(console.ctx, "payments")
    assert cov["source"] != "cov_src_capabilities" and cov["planned"] == 2 and cov["caps"] == 3
    r = console.get("/console/agents/payments")
    card = r.text.split('data-agent="payments"', 1)[1].split("</article>", 1)[0]
    assert "2 of 3 monitoring capabilities planned by Onboard" in card
    state.update("coverage", {"agent_id": "payments", "capability_id": "cap0"}, {"status": "on"}, 1)
    cov = _coverage(console.ctx, "payments")
    assert cov["source"] == "cov_src_capabilities" and cov["bp"] == 3333


def test_resume_shows_pending_approval(console: Console) -> None:
    p = console.post("/console/agents/payments/pause", {"reason": "x"})
    assert p.status_code == 200 and "by reviewer.an" in p.text
    r = console.post("/console/agents/payments/resume", {"reason": "ok"})
    assert r.status_code == 200 and "needs the owner" in r.text
    card = r.text.split('data-agent="payments"', 1)[1].split("</article>", 1)[0]
    assert 'data-pending="1"' in card and "Waiting for the owner." in card
    assert "Approved by reviewer.an" in card
    assert "disabled" in card  # the same person cannot approve twice
    owner = console.get("/console/agents/payments", user="payops-lead@example.invalid")
    card = owner.text.split('data-agent="payments"', 1)[1].split("</article>", 1)[0]
    assert "Give the second approval" in card and "You are the owner." in card

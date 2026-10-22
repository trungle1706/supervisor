"""WP-G6 governance tools: reads in scope, writes as drafts, confirm before write, audit."""

from __future__ import annotations

from typing import Any

import pytest

from supervisor.console import systems_wizard

from .conftest import Cred, Rig

DRAFT: dict[str, Any] = {
    "name": "Pay assist",
    "owner_team": "Payments Ops",
    "purpose": "Answers staff questions about transfers.",
    "system_type": "assistant",
    "org_role": "deployer",
    "user_segment": "internal",
    "personal_data": "none",
    "human_control": "post_review",
}


def register(rig: Rig, cred: Cred, **over: Any) -> str:
    out = rig.ok(cred, "register_system", {"draft": {**DRAFT, **over}, "confirm": True})
    return str(out["system_id"])


# ------------------------------------------------------------------------ register_system


def test_register_without_confirm_plans_and_writes_nothing(rig: Rig) -> None:
    cred = rig.new_app()
    out = rig.ok(cred, "register_system", {"draft": DRAFT})
    assert out["written"] is False and out["confirm_required"] is True
    plan = out["planned_change"]
    assert plan["status"] == "draft" and plan["lifecycle_stage"] == "initiation"
    assert plan["decision33_class"] == "unclassified"
    assert rig.ctx.state.query("ai_system") == []
    assert [r for r in rig.actions() if r["path"].startswith("/mcp/tools")] == []  # no row


def test_register_with_confirm_writes_a_draft_and_two_audit_rows(rig: Rig) -> None:
    cred = rig.new_app()
    sid = register(rig, cred)
    row = rig.ctx.state.get("ai_system", {"system_id": sid})
    assert row["status"] == "draft" and row["lifecycle_stage"] == "initiation"
    assert row["decision33_class"] == "unclassified" and row["created_by"] == f"mcp:{cred.app_id}"
    rows = [r for r in rig.actions() if r["path"] == "/mcp/tools/register_system"]
    assert [r["outcome"] for r in rows] == ["attempted", "ok"]
    assert {r["request_id"] for r in rows} == {rows[0]["request_id"]}
    assert rows[0]["actor"] == f"mcp:{cred.app_id}" and rows[0]["method"] == "MCP"
    assert rows[1]["target_kind"] == "system" and rows[1]["target_id"] == sid
    assert rows[0]["before_hash"] is None and rows[1]["after_hash"]
    # the same chain record as the API writes
    assert rig.ctx.systems.get(sid)["name"] == "Pay assist"


@pytest.mark.parametrize(
    ("over", "text"),
    [
        ({"decision33_class": "not_high_risk"}, "cannot carry"),
        ({"risk_level": "low"}, "cannot carry"),
        ({"risk_justification": "x"}, "cannot carry"),
        ({"business_impact": "low"}, "cannot carry"),
        ({"status": "active"}, "cannot carry"),
        ({"lifecycle_stage": "design"}, "cannot carry"),
        ({"colour": "red"}, "unknown field"),
        ({"system_type": "robot"}, "system_type"),
        ({"autonomy_level": "l1_assistive"}, "cannot carry"),
        ({"owner_user": "reviewer.an"}, "owner_user must be"),
    ],
)
def test_a_draft_cannot_classify_or_set_the_level(
    rig: Rig, over: dict[str, Any], text: str
) -> None:
    cred = rig.new_app()
    err = rig.err(cred, "register_system", {"draft": {**DRAFT, **over}, "confirm": True})
    assert err["code"] == -32602 and text in err["message"]
    assert rig.ctx.state.query("ai_system") == []


def test_a_duplicate_name_is_a_message_not_a_crash(rig: Rig) -> None:
    cred = rig.new_app()
    register(rig, cred)
    err = rig.err(cred, "register_system", {"draft": DRAFT, "confirm": True})
    assert err["code"] == -32602 and "already used" in err["message"]


@pytest.mark.parametrize("roles", [("reviewer",), ("auditor", "reviewer")])
def test_an_app_registers_only_as_the_owner_of_its_own_draft(
    rig: Rig, roles: tuple[str, ...]
) -> None:
    """L2: for every app, not only a scoped one."""
    cred = rig.new_app("owner app", roles=roles)
    me = f"mcp:{cred.app_id}"
    err = rig.err(
        cred, "register_system", {"draft": {**DRAFT, "owner_user": "someone"}, "confirm": True}
    )
    assert err["code"] == -32602 and me in err["message"]
    sid = rig.ok(cred, "register_system", {"draft": {**DRAFT, "owner_user": me}, "confirm": True})[
        "system_id"
    ]
    assert rig.ctx.state.get("ai_system", {"system_id": sid})["owner_user"] == me
    other = rig.ok(
        cred, "register_system", {"draft": {**DRAFT, "name": "Left out"}, "confirm": True}
    )
    assert rig.ctx.state.get("ai_system", {"system_id": other["system_id"]})["owner_user"] == me


def test_confirm_must_be_a_boolean(rig: Rig) -> None:
    cred = rig.new_app()
    for bad in ("true", 1, None, "yes", [True]):
        out = rig.call(cred, "register_system", {"draft": DRAFT, "confirm": bad})
        assert out["error"]["code"] == -32602 and "confirm" in out["error"]["message"]
    assert rig.ctx.state.query("ai_system") == []


# ------------------------------------------------------------------------ scope and reads


def test_a_viewer_app_sees_only_the_systems_it_is_on(rig: Rig) -> None:
    boss = rig.new_app("boss")
    sid = register(rig, boss)
    register(rig, boss, name="Other system")
    viewer = rig.new_app("viewer app", roles=("viewer",))
    assert rig.ok(viewer, "list_entities", {"kind": "system"})["count"] == 0
    err = rig.err(viewer, "get_entity", {"kind": "system", "id": sid})
    assert err["code"] == -32004 and "does not exist" in err["message"]  # same as a missing one
    assert rig.err(viewer, "get_entity", {"kind": "system", "id": "sys_nothing"})["code"] == -32004
    rig.ctx.systems.add_member(sid, f"mcp:{viewer.app_id}", "technical_specialist", "reviewer.an")
    seen = rig.ok(viewer, "list_entities", {"kind": "system"})
    assert [i["system_id"] for i in seen["items"]] == [sid]
    assert (
        rig.ok(viewer, "get_entity", {"kind": "system", "id": sid})["item"]["name"] == "Pay assist"
    )
    assert rig.ok(boss, "list_entities", {"kind": "system"})["count"] == 2


def test_list_filters_limits_and_bad_input(rig: Rig) -> None:
    cred = rig.new_app()
    register(rig, cred)
    register(rig, cred, name="Second", system_type="decision")
    ok = rig.ok(cred, "list_entities", {"kind": "system", "filters": {"system_type": "decision"}})
    assert [i["name"] for i in ok["items"]] == ["Second"]
    one = rig.ok(cred, "list_entities", {"kind": "system", "limit": 1})
    assert one["count"] == 2 and one["truncated"] is True and len(one["items"]) == 1
    for args, code in (
        ({"kind": "planet"}, -32602),
        ({"kind": "system", "filters": {"nope": "1"}}, -32602),
        ({"kind": "system", "filters": {"status": 1}}, -32602),
        ({"kind": "system", "filters": [1]}, -32602),
        ({"kind": "system", "limit": 0}, -32602),
        ({"kind": "system", "limit": 5000}, -32602),
        ({"kind": "system", "extra": 1}, -32602),
        ({}, -32602),
    ):
        assert rig.err(cred, "list_entities", args)["code"] == code


def test_the_other_entity_kinds(rig: Rig) -> None:
    cred = rig.new_app()
    assert rig.ok(cred, "list_entities", {"kind": "risk"})["kind"] == "risk"
    assert rig.ok(cred, "list_entities", {"kind": "control"})["kind"] == "control"
    assert rig.ok(cred, "list_entities", {"kind": "review"})["items"] == []
    err = rig.err(cred, "list_entities", {"kind": "incident"})  # GOVERNANCE_ACTIONS_ENABLED off
    assert "GOVERNANCE_ACTIONS_ENABLED" in err["message"]
    rig.ctx.settings.governance_actions_enabled = True
    assert rig.ok(cred, "list_entities", {"kind": "incident"})["items"] == []
    assert rig.err(cred, "get_entity", {"kind": "incident", "id": "inc_none"})["code"] == -32004
    assert rig.err(cred, "get_entity", {"kind": "review", "id": "rv_none"})["code"] == -32004
    assert rig.err(cred, "get_entity", {"kind": "risk", "id": "RSK-NONE"})["code"] == -32004
    assert rig.err(cred, "get_entity", {"kind": "control", "id": "CTL-NONE"})["code"] == -32004


def test_governance_tools_say_so_when_governance_is_off(rig: Rig) -> None:
    cred = rig.new_app()
    rig.ctx.settings.governance_enabled = False
    err = rig.err(cred, "list_entities", {"kind": "system"})
    assert err["code"] == -32602 and "GOVERNANCE_ENABLED" in err["message"]


# ------------------------------------------------------------------------ link_component


def test_link_component(rig: Rig) -> None:
    cred = rig.new_app()
    sid = register(rig, cred)
    args = {"system_id": sid, "ref_kind": "agent", "ref_id": "payments"}
    plan = rig.ok(cred, "link_component", args)
    assert plan["written"] is False and plan["planned_change"]["role"] == "component_of"
    assert rig.ctx.systems.get(sid)["components"] == []
    out = rig.ok(cred, "link_component", {**args, "confirm": True})
    assert out["components"][0]["ref_id"] == "payments"
    rows = [r for r in rig.actions() if r["path"] == "/mcp/tools/link_component"]
    assert [r["outcome"] for r in rows] == ["attempted", "ok"]
    assert rows[1]["before_hash"] != rows[1]["after_hash"] and rows[1]["target_id"] == sid
    again = rig.ok(cred, "link_component", {**args, "confirm": True})  # a repeat is a no-op
    assert len(again["components"]) == 1
    for bad in (
        {**args, "ref_kind": "model"},
        {**args, "role": "owner"},
        {**args, "ref_id": "bad id"},
    ):
        assert rig.err(cred, "link_component", {**bad, "confirm": True})["code"] == -32602
    assert (
        rig.err(cred, "link_component", {**args, "system_id": "sys_none", "confirm": True})["code"]
        == -32004
    )


def test_a_viewer_role_cannot_link(rig: Rig) -> None:
    boss = rig.new_app("boss")
    sid = register(rig, boss)
    viewer = rig.new_app("viewer app", roles=("viewer",))
    err = rig.err(
        viewer,
        "link_component",
        {"system_id": sid, "ref_kind": "agent", "ref_id": "payments", "confirm": True},
    )
    assert err["code"] == -32003


# ------------------------------------------------------------------------ propose_risk

RISK: dict[str, Any] = {
    "agent_id": "payments",
    "title": "Wrong payee on a transfer",
    "description": "The agent picks the wrong payee.",
    "category": "money_movement",
    "inherent_likelihood": 3,
    "inherent_impact": 4,
    "treatment": "mitigate",
    "owner": "Payments Ops",
}


def test_propose_risk_is_a_draft_never_active(rig: Rig) -> None:
    cred = rig.new_app()
    sid = register(rig, cred)
    rig.ok(
        cred,
        "link_component",
        {"system_id": sid, "ref_kind": "agent", "ref_id": "payments", "confirm": True},
    )
    args = {"system_id": sid, **RISK}
    plan = rig.ok(cred, "propose_risk", args)
    assert plan["written"] is False and plan["planned_change"]["status"] == "draft"
    assert rig.ctx.state.query("risk") == []
    out = rig.ok(cred, "propose_risk", {**args, "confirm": True})
    row = rig.ctx.state.get("risk", {"risk_id": out["risk_id"]})
    assert out["status"] == "draft" and row["status"] == "draft"
    assert row["created_by"] == f"mcp:{cred.app_id}" and row["agent_id"] == "payments"
    rows = [r for r in rig.actions() if r["path"] == "/mcp/tools/propose_risk"]
    assert [r["outcome"] for r in rows] == ["attempted", "ok"] and rows[1]["target_kind"] == "risk"
    assert rows[1]["target_id"] == out["risk_id"]


@pytest.mark.parametrize(
    ("over", "text"),
    [
        ({"treatment": "accept"}, "one of"),  # the schema does not even list accept
        ({"agent_id": "customer_service"}, "not linked"),
        ({"category": "weather"}, "category"),
        ({"inherent_likelihood": 9}, "at most"),
        ({"residual_likelihood": 5}, "above the inherent"),
        ({"title": ""}, "required"),
        ({"status": "active"}, "unknown argument"),
        ({"source": "starter"}, "unknown argument"),
    ],
)
def test_a_risk_proposal_is_checked_like_the_api(rig: Rig, over: dict[str, Any], text: str) -> None:
    cred = rig.new_app()
    sid = rig.ok(cred, "register_system", {"draft": DRAFT, "confirm": True})["system_id"]
    rig.ok(
        cred,
        "link_component",
        {"system_id": sid, "ref_kind": "agent", "ref_id": "payments", "confirm": True},
    )
    err = rig.err(cred, "propose_risk", {"system_id": sid, **RISK, **over, "confirm": True})
    assert err["code"] == -32602 and text in err["message"], err
    assert rig.ctx.state.query("risk") == []


def test_accept_is_refused_with_a_message_for_a_person(rig: Rig) -> None:
    """The schema lists no accept; a client that skips the schema check still gets the message."""
    from supervisor.mcp_server.registry import validate_args  # noqa: F401

    cred = rig.new_app()
    sid = register(rig, cred)
    rig.ok(
        cred,
        "link_component",
        {"system_id": sid, "ref_kind": "agent", "ref_id": "payments", "confirm": True},
    )
    from types import SimpleNamespace

    from supervisor.core.errors import SupervisorError
    from supervisor.mcp_server import tools_governance as tg
    from supervisor.mcp_server.protocol import Caller

    caller = Caller(
        ctx=rig.ctx,
        app={},
        principal=SimpleNamespace(user_id="mcp:x", roles=frozenset({"reviewer"})),
        scopes=frozenset(),
        request_id="r",
        approved=True,
    )
    with pytest.raises(SupervisorError, match="decision of a person"):
        tg.propose_risk(caller, {"system_id": sid, **RISK, "treatment": "accept"}, False)


def test_a_risk_proposal_needs_the_register(rig: Rig) -> None:
    cred = rig.new_app()
    sid = register(rig, cred)
    rig.ctx.settings.risk_register_enabled = False
    err = rig.err(cred, "propose_risk", {"system_id": sid, **RISK, "confirm": True})
    assert "RISK_REGISTER_ENABLED" in err["message"]


# ------------------------------------------------------------------------ tasks


def test_list_and_complete_tasks(rig: Rig) -> None:
    cred = rig.new_app("task app", roles=("reviewer", "owner"))
    sid = register(rig, cred)
    systems_wizard.open_tasks(rig.ctx, sid, "reviewer.an")
    tasks = rig.ok(cred, "list_tasks", {"system_id": sid})
    assert tasks["count"] >= 2 and all(t["status"] == "open" for t in tasks["items"])
    tid = tasks["items"][0]["task_id"]
    plan = rig.ok(cred, "complete_task", {"task_id": tid})
    assert plan["written"] is False and plan["planned_change"]["to_status"] == "done"
    assert rig.ctx.tasks.get(tid)["status"] == "open"
    out = rig.ok(cred, "complete_task", {"task_id": tid, "confirm": True})
    assert out["status"] == "done"
    assert rig.ctx.tasks.get(tid)["done_by"] == f"mcp:{cred.app_id}"
    rows = [r for r in rig.actions() if r["path"] == "/mcp/tools/complete_task"]
    assert [r["outcome"] for r in rows] == ["attempted", "ok"] and rows[1]["target_id"] == tid
    err = rig.err(cred, "complete_task", {"task_id": tid, "confirm": True})
    assert err["code"] == -32602 and "cannot be marked done" in err["message"]


def test_a_task_of_another_role_or_a_move_is_refused(rig: Rig) -> None:
    boss = rig.new_app("boss", roles=("reviewer", "owner"))
    sid = register(rig, boss)
    systems_wizard.open_tasks(rig.ctx, sid, "reviewer.an")
    tid = rig.ok(boss, "list_tasks", {"system_id": sid})["items"][0]["task_id"]
    only_reviewer = rig.new_app("reviewer only", roles=("reviewer",))
    err = rig.err(only_reviewer, "complete_task", {"task_id": tid, "confirm": True})
    assert err["code"] == -32602 and "belongs to role owner" in err["message"]
    assert rig.ctx.tasks.get(tid)["status"] == "open"
    # a lifecycle move or an approver task is a person's decision
    for kind, role in (("move", "owner"), ("task", "approver")):
        row = rig.ctx.tasks._row_for(  # noqa: SLF001
            sid, "initiation", template_id=f"X-{kind}", kind="custom", title="t",
            owner_role=role, required=True, due_days=5, evidence_kind="none",
            evidence_ref=None, level="low", d33_class="unclassified", actor="reviewer.an",
        )  # fmt: skip
        row["kind"] = "move" if kind == "move" else "custom"
        rig.ctx.tasks._insert(row, "reviewer.an")  # noqa: SLF001
        err = rig.err(boss, "complete_task", {"task_id": row["task_id"], "confirm": True})
        assert "a person closes it in the console" in err["message"]


def test_a_task_outside_the_scope_does_not_exist(rig: Rig) -> None:
    boss = rig.new_app("boss", roles=("reviewer", "owner"))
    sid = register(rig, boss)
    systems_wizard.open_tasks(rig.ctx, sid, "reviewer.an")
    tid = rig.ok(boss, "list_tasks", {"system_id": sid})["items"][0]["task_id"]
    viewer = rig.new_app("viewer app", roles=("viewer", "owner"))
    err = rig.err(viewer, "complete_task", {"task_id": tid, "confirm": True})
    assert err["code"] == -32004
    assert rig.err(viewer, "list_tasks", {"system_id": sid})["code"] == -32004
    assert (
        rig.err(boss, "complete_task", {"task_id": "tsk_none", "confirm": True})["code"] == -32004
    )


# ------------------------------------------------------------------------ others


def test_transparency_report_of_the_agents_of_a_system(rig: Rig) -> None:
    cred = rig.new_app()
    sid = register(rig, cred)
    rig.ok(
        cred,
        "link_component",
        {"system_id": sid, "ref_kind": "agent", "ref_id": "payments", "confirm": True},
    )
    out = rig.ok(cred, "transparency_report", {"system_id": sid, "variant": "regulator"})
    assert out["agents"][0]["agent_id"] == "payments"
    assert out["agents"][0]["info"]["status"] in ("preview", "signed")
    assert (
        rig.err(cred, "transparency_report", {"system_id": sid, "variant": "secret"})["code"]
        == -32602
    )
    rig.ctx.settings.transparency_enabled = False
    assert (
        "TRANSPARENCY_ENABLED"
        in rig.err(cred, "transparency_report", {"system_id": sid, "variant": "internal"})[
            "message"
        ]
    )


def test_classification_draft_is_a_draft_only(rig: Rig) -> None:
    cred = rig.new_app()
    sid = register(rig, cred)
    plan = rig.ok(cred, "classification_draft", {"system_id": sid})
    assert plan["planned_change"]["applies"] is False
    assert rig.ctx.state.query("classification") == []
    out = rig.ok(cred, "classification_draft", {"system_id": sid, "confirm": True})
    assert out["classification"]["status"] == "draft"
    row = rig.ctx.state.get("ai_system", {"system_id": sid})
    assert row["decision33_class"] == "unclassified"  # only a person applies it
    rows = [r for r in rig.actions() if r["path"] == "/mcp/tools/classification_draft"]
    assert [r["outcome"] for r in rows] == ["attempted", "ok"]


def test_the_kpis_tool_is_the_kpi_function(rig: Rig) -> None:
    from supervisor.governance import kpis
    from supervisor.mcp_server.common import plain

    cred = rig.new_app()
    register(rig, cred)
    out = rig.ok(cred, "kpis")
    from supervisor.mcp_server.auth import principal_of

    me = principal_of({"app_id": cred.app_id}, ["reviewer"])
    want = plain(kpis.compute(rig.ctx, me))
    out.pop("generated_at"), want.pop("generated_at")
    assert out == want and out["coverage"]["systems_total"] == 1

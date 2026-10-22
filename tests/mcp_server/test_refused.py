"""WP-G6: no tool takes a decision that belongs to a person. The registry refuses such names at
registration, and a test enumerates the tools that exist."""

from __future__ import annotations

import pytest

from supervisor.mcp_server.registry import (
    REFUSED_NAMES,
    REFUSED_PARTS,
    RefusedTool,
    Registry,
    Tool,
    refusal_for,
)
from supervisor.mcp_server.server import build_registry

from .conftest import Rig

# What a person decides, in many spellings: none may become a tool.
FORBIDDEN = [
    "classify",
    "classify_system",
    "apply_classification",
    "classification_apply",
    "approve",
    "approve_stage",
    "approve_task",
    "approve_app",
    "decide_approval",
    "sign_off",
    "signoff",
    "accept_risk",
    "risk_accept",
    "set_risk_level",
    "change_risk_level",
    "lower_risk_level",
    "raise_risk_level",
    "update_risk_level",
    "close_incident",
    "resolve_incident",
    "transition_incident",
    "disable_guardian",
    "turn_off_guardian",
    "guardian_off",
    "pause_agent",
    "resume_agent",
    "quarantine_agent",
    "waive_task",
    "Approve-Stage",
]
WRITE_TOOLS = {
    "register_system",
    "link_component",
    "propose_risk",
    "complete_task",
    "classification_draft",
    "chain_verify",  # a write in disguise (review M1): it records a chain entry
}


def noop(call: object, args: dict[str, object], apply: bool) -> dict[str, object]:
    return {}


@pytest.mark.parametrize("name", FORBIDDEN)
def test_a_refused_name_cannot_be_registered(name: str) -> None:
    reg = Registry()
    with pytest.raises(RefusedTool, match="console"):
        reg.register(
            Tool(name.lower().replace("-", "_"), "x", "governance.write", {}, noop, write=True)
        )
    assert len(reg) == 0
    assert refusal_for(name)


def test_the_registered_tools_are_not_on_the_refusal_list() -> None:
    reg = build_registry()
    names = reg.names()
    assert len(names) == len(set(names)) and len(names) >= 18
    for name in names:
        assert refusal_for(name) is None, name
        assert name not in REFUSED_NAMES, name
        assert not any(part in name for part in REFUSED_PARTS), name
    for name in FORBIDDEN:
        assert name.lower().replace("-", "_") not in names


def test_the_write_tools_are_exactly_the_draft_tools() -> None:
    reg = build_registry()
    assert {t.name for t in reg if t.write} == WRITE_TOOLS
    for t in reg:
        if t.write:
            assert t.scope in ("governance.write", "supervisor.read")
            assert (t.scope == "governance.write") == (t.name != "chain_verify")
            assert t.permission and t.target
            assert "confirm" in t.listing()["inputSchema"]["properties"]
        else:
            assert "confirm" not in t.listing()["inputSchema"]["properties"]
            assert t.listing()["annotations"]["readOnlyHint"] is True
        assert t.listing()["inputSchema"]["additionalProperties"] is False


def test_tool_groups_and_scopes() -> None:
    by_scope: dict[str, set[str]] = {}
    for t in build_registry():
        by_scope.setdefault(t.scope, set()).add(t.name)
    assert by_scope["library.read"] == {
        "regulations",
        "obligations",
        "starter_risks",
        "starter_controls",
        "guardian_catalog",
        "assignment_rules",
    }
    assert by_scope["supervisor.read"] == {
        "gate_state",
        "decisions",
        "findings",
        "chain_verify",
        "pack_results",
    }
    assert by_scope["governance.write"] == WRITE_TOOLS - {"chain_verify"}
    assert {"list_entities", "get_entity", "list_tasks", "transparency_report"} <= by_scope[
        "governance.read"
    ]


VERBS = [
    "accept", "approve", "apply", "lower", "downgrade", "close", "resolve", "pause", "resume",
    "halt", "suspend", "quarantine", "release", "retire", "disable", "waive", "certify",
    "authorize", "authorise", "promote", "advance", "activate", "decide", "set", "classify",
    "signoff",
]  # fmt: skip
NOUNS = ["risk", "system", "agent", "incident", "task", "stage", "control", "report"]


def probe_names() -> list[str]:
    """The reviewer's probe: every verb with several nouns, in two orders, plus prefixes."""
    out = [f"{v}_{n}" for v in VERBS for n in NOUNS]
    out += [f"{n}_{v}" for v in VERBS[:12] for n in NOUNS[:3]]
    out += ["set_anything", "set_flag", "off", "turn_off", "guardian_off", "stage_advance"]
    return sorted(set(out))


def test_the_probe_list_is_long_enough_and_every_name_is_refused() -> None:
    names = probe_names()
    assert len(names) >= 130
    free = [n for n in names if refusal_for(n) is None]
    assert not free, free
    for name in names:
        reg = Registry()
        with pytest.raises(RefusedTool):
            reg.register(Tool(name, "x", "governance.write", {}, noop, write=True))


def test_a_verb_is_refused_inside_any_name_but_the_existing_tools_pass() -> None:
    for name in ("list_and_approve", "quick_resume_all", "x_set_y", "bulk_release", "auto_waive"):
        assert refusal_for(name)
    for name in build_registry().names():
        assert refusal_for(name) is None
    for name in ("list_things", "get_report", "propose_change", "register_thing", "count_items"):
        assert refusal_for(name) is None  # a draft or a read verb is fine


def test_a_second_registration_or_a_bad_scope_is_refused() -> None:
    reg = Registry()
    reg.register(Tool("fine_tool", "x", "library.read", {}, noop))
    with pytest.raises(ValueError, match="twice"):
        reg.register(Tool("fine_tool", "x", "library.read", {}, noop))
    with pytest.raises(ValueError, match="scope"):
        reg.register(Tool("other_tool", "x", "root.all", {}, noop))
    with pytest.raises(ValueError, match="write tool"):
        reg.register(Tool("put_thing", "x", "library.read", {}, noop, write=True))
    with pytest.raises(ValueError, match="bad tool name"):
        reg.register(Tool("Bad Name", "x", "library.read", {}, noop))


def test_a_call_to_a_refused_name_over_the_wire_is_an_unknown_tool(rig: Rig) -> None:
    """The server has no such tool, so the answer is the same as for any unknown name."""
    cred = rig.new_app()
    for name in ("approve_stage", "accept_risk", "classify_system", "close_incident"):
        err = rig.err(cred, name, {"system_id": "sys_x"})
        assert err["code"] == -32602 and "unknown tool" in err["message"]
    listed = {t["name"] for t in rig.rpc(cred, "tools/list").json()["result"]["tools"]}
    assert listed == set(build_registry().names())

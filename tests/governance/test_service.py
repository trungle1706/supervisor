"""WP-G0 service: enums, scoping per role, segregation of duties, inheritance, chain record."""

from __future__ import annotations

import json
from typing import Any

import pytest

from supervisor.adapters.factory import Adapters
from supervisor.core import rbac
from supervisor.core.errors import NotFoundError
from supervisor.governance import model
from supervisor.governance.model import SegregationOfDuties, SystemsError
from supervisor.governance.systems import (
    ALL,
    ALL_ROLES,
    SCOPED_ROLES,
    SystemService,
    system_id_for,
)
from supervisor.inventory.graph import Graph
from supervisor.inventory.model import Node
from supervisor.inventory.store import InventoryStore

from .conftest import ListSink, add_agent, draft, person


def _make(svc: SystemService, **over: Any) -> dict[str, Any]:
    return svc.register(draft(**over), "owner.lan")


# ------------------------------------------------------------------ enums and intake


def test_register_stores_a_draft_with_defaults(svc: SystemService) -> None:
    s = _make(svc)
    assert s["system_id"] == system_id_for("Payments - Assistant")
    assert s["status"] == "draft" and s["lifecycle_stage"] == "initiation"
    assert s["risk_level"] == "unspecified" and s["risk_level_source"] == "manual"
    assert s["decision33_class"] == "unclassified" and s["business_impact"] == "unspecified"
    assert s["money_movement"] is False and s["credit_decision"] is False
    assert s["tags"] == {}
    assert [(m["user_id"], m["team_role"]) for m in s["team"]] == [("owner.lan", "system_owner")]
    assert s["effective_risk"]["level"] == "unspecified"


@pytest.mark.parametrize(
    ("field", "bad"),
    [
        ("system_type", "robot"),
        ("org_role", "vendor"),
        ("user_segment", "public"),
        ("personal_data", "some"),
        ("human_control", "always"),
        ("lifecycle_stage", "launch"),
        ("risk_level", "critical"),
        ("decision33_class", "maybe"),
        ("business_impact", "huge"),
        ("money_movement", "perhaps"),
        ("tags", ["a"]),
        ("name", ""),
        ("owner_user", "bad user<script>"),
    ],
)
def test_bad_enum_is_refused_with_a_message(svc: SystemService, field: str, bad: Any) -> None:
    with pytest.raises(SystemsError) as exc:
        svc.register(draft(**{field: bad}), "owner.lan")
    assert field in str(exc.value)


def test_missing_required_unknown_and_status_are_refused(svc: SystemService) -> None:
    bad = draft()
    del bad["purpose"]
    with pytest.raises(SystemsError, match="required: purpose"):
        svc.register(bad, "x")
    with pytest.raises(SystemsError, match="unknown field"):
        svc.register(draft(colour="red"), "x")
    with pytest.raises(SystemsError, match="starts as draft"):
        svc.register(draft(status="active"), "x")


def test_name_is_unique_ignoring_case_and_spacing(svc: SystemService) -> None:
    _make(svc)
    with pytest.raises(SystemsError, match="already"):
        _make(svc, name="  payments -   assistant ")
    other = _make(svc, name="Payments - Scoring")
    with pytest.raises(SystemsError, match="already used"):
        svc.update_fields(other["system_id"], {"name": "payments - assistant"}, "owner.lan")


def test_every_vocabulary_value_is_accepted(svc: SystemService) -> None:
    for i, (field, values) in enumerate(
        [
            ("system_type", model.SYSTEM_TYPES),
            ("org_role", model.ORG_ROLES),
            ("user_segment", model.USER_SEGMENTS),
            ("personal_data", model.PERSONAL_DATA),
            ("human_control", model.HUMAN_CONTROLS),
        ]
    ):
        for v in values:
            _make(svc, name=f"sys {i} {v}", **{field: v})
    s = _make(svc, name="levels")
    for field, values in [
        ("lifecycle_stage", model.LIFECYCLE_STAGES),
        ("risk_level", model.RISK_LEVELS),
        ("decision33_class", model.DECISION33_CLASSES),
        ("business_impact", model.BUSINESS_IMPACTS),
    ]:
        for v in values:
            assert svc.update_fields(s["system_id"], {field: v}, "owner.lan")[field] == v


def test_update_archive_and_concurrency(svc: SystemService) -> None:
    s = _make(svc)
    sid = s["system_id"]
    u = svc.update_fields(
        sid,
        {"purpose": "New purpose", "tags": {"env": "prod", "region": "vn"}, "status": "active"},
        "owner.lan",
    )
    assert u["purpose"] == "New purpose" and u["status"] == "active"
    assert u["tags"] == {"env": "prod", "region": "vn"}
    with pytest.raises(SystemsError, match="cannot change"):
        svc.update_fields(sid, {"created_by": "x"}, "owner.lan")
    with pytest.raises(SystemsError, match="cannot change"):
        svc.update_fields(sid, {"system_id": "x"}, "owner.lan")
    with pytest.raises(SystemsError, match="status must be one of"):
        svc.update_fields(sid, {"status": "archived"}, "owner.lan")
    with pytest.raises(SystemsError, match="changed by someone else"):
        svc.update_fields(sid, {"purpose": "x"}, "owner.lan", expected_version=1)
    a = svc.archive(sid, "owner.lan")
    assert a["status"] == "archived"
    for call in (
        lambda: svc.update_fields(sid, {"purpose": "x"}, "owner.lan"),
        lambda: svc.add_member(sid, "u1", "reviewer", "owner.lan"),
        lambda: svc.link(sid, "agent", "a", "owner.lan"),
        lambda: svc.archive(sid, "owner.lan"),
    ):
        with pytest.raises(SystemsError, match="archived"):
            call()
    with pytest.raises(NotFoundError):
        svc.get("sys_nope")
    with pytest.raises(SystemsError):
        svc.get("bad id!")


# ------------------------------------------------------------------ team and SoD


def test_segregation_of_duties(svc: SystemService) -> None:
    sid = _make(svc)["system_id"]
    # the owner cannot be reviewer or oversight manager of the same system
    for role in ("reviewer", "oversight_manager"):
        with pytest.raises(SegregationOfDuties, match="^segregation of duties:"):
            svc.add_member(sid, "owner.lan", role, "owner.lan")
    # a reviewer cannot become system_owner, directly or by an owner change
    svc.add_member(sid, "rev.binh", "reviewer", "owner.lan")
    svc.add_member(sid, "ovs.chi", "oversight_manager", "owner.lan")
    for who in ("rev.binh", "ovs.chi"):
        with pytest.raises(SegregationOfDuties, match="^segregation of duties:"):
            svc.add_member(sid, who, "system_owner", "owner.lan")
        with pytest.raises(SegregationOfDuties, match="^segregation of duties:"):
            svc.update_fields(sid, {"owner_user": who}, "owner.lan")
    # a second system_owner cannot be turned into a reviewer either
    svc.add_member(sid, "co.owner", "system_owner", "owner.lan")
    with pytest.raises(SegregationOfDuties):
        svc.add_member(sid, "co.owner", "reviewer", "owner.lan")
    # registering with the business owner equal to the owner is fine; roles unchanged
    assert {m["user_id"]: m["team_role"] for m in svc.get(sid)["team"]} == {
        "owner.lan": "system_owner",
        "rev.binh": "reviewer",
        "ovs.chi": "oversight_manager",
        "co.owner": "system_owner",
    }


def test_owner_change_moves_the_owner_role(svc: SystemService) -> None:
    sid = _make(svc)["system_id"]
    svc.add_member(sid, "tech.minh", "technical_specialist", "owner.lan")
    s = svc.update_fields(sid, {"owner_user": "tech.minh"}, "owner.lan")
    assert s["owner_user"] == "tech.minh"
    roles = {m["user_id"]: m["team_role"] for m in s["team"]}
    assert roles["tech.minh"] == "system_owner"
    with pytest.raises(SystemsError, match="cannot be removed"):
        svc.remove_member(sid, "tech.minh", "owner.lan")


def test_team_add_change_remove(svc: SystemService) -> None:
    sid = _make(svc, business_owner="biz.tam")["system_id"]
    assert {m["user_id"]: m["team_role"] for m in svc.get(sid)["team"]}["biz.tam"] == (
        "business_owner"
    )
    svc.add_member(sid, "d.steward", "data_steward", "owner.lan")
    svc.add_member(sid, "d.steward", "compliance_specialist", "owner.lan")
    team = {m["user_id"]: m["team_role"] for m in svc.get(sid)["team"]}
    assert team["d.steward"] == "compliance_specialist"
    with pytest.raises(SystemsError, match="team_role must be one of"):
        svc.add_member(sid, "x", "boss", "owner.lan")
    with pytest.raises(SystemsError, match="keeps the system_owner role"):
        svc.add_member(sid, "owner.lan", "data_steward", "owner.lan")
    svc.remove_member(sid, "d.steward", "owner.lan")
    assert "d.steward" not in {m["user_id"] for m in svc.get(sid)["team"]}
    with pytest.raises(NotFoundError):
        svc.remove_member(sid, "d.steward", "owner.lan")
    svc.add_member(sid, "d.steward", "data_steward", "owner.lan")  # comes back
    assert "d.steward" in {m["user_id"] for m in svc.get(sid)["team"]}


# ------------------------------------------------------------------ links and inheritance


def _inventory(adapters: Adapters) -> Graph:
    g = Graph()
    agent = Node("system", "pay-bot", attrs={"role": "agent"})
    tool = Node("tool", "pay-bot:transfer", own_risk="critical", risk_source="manifest")
    safe = Node("tool", "pay-bot:balance", own_risk="low", risk_source="manifest")
    other = Node("system", "faq-bot", attrs={"role": "agent"})
    model_node = Node("model", "qwen3", own_risk="medium", risk_source="manifest")
    g.link(agent, "uses", tool, "manifest", "m:1")
    g.link(agent, "uses", safe, "manifest", "m:2")
    g.link(other, "uses", model_node, "manifest", "m:3")
    for n in (agent, tool, safe, other, model_node):
        g.add_node(n)
    InventoryStore(adapters.state, adapters.clock).apply(g, source="manifest")
    return g


def test_effective_risk_is_the_max_of_manual_and_inherited(
    svc: SystemService, adapters: Adapters
) -> None:
    g = _inventory(adapters)
    add_agent(adapters, "pay-bot")
    add_agent(adapters, "faq-bot")
    sid = _make(svc)["system_id"]
    assert svc.effective_risk_level(sid).level == "unspecified"
    svc.link(sid, "agent", "faq-bot", "owner.lan")
    er = svc.effective_risk_level(sid)
    assert (er.level, er.source, er.inherited_level) == ("medium", "inherited", "medium")
    # a lower manual level does not win; the source says so
    svc.update_fields(sid, {"risk_level": "low"}, "owner.lan")
    assert svc.effective_risk_level(sid).source == "inherited"
    # a critical tool is "high" at the system (the system scale has no critical)
    svc.link(sid, "agent", "PAY-BOT", "owner.lan")  # id case does not matter
    er = svc.effective_risk_level(sid)
    assert (er.level, er.source) == ("high", "inherited")
    assert {(v["ref_id"], v["level"]) for v in er.via} == {
        ("faq-bot", "medium"),
        ("pay-bot", "high"),
    }
    # a manual prohibited wins over everything; a manual equal level keeps manual
    svc.update_fields(sid, {"risk_level": "prohibited"}, "owner.lan")
    er = svc.effective_risk_level(sid)
    assert (er.level, er.source) == ("prohibited", "manual")
    svc.update_fields(sid, {"risk_level": "high", "risk_level_source": "classifier"}, "owner.lan")
    er = svc.effective_risk_level(sid)
    assert (er.level, er.source) == ("high", "classifier")
    # a node can be linked too; an inventory node's effective level counts
    node_id = next(nid for nid, n in g.nodes.items() if n.name == "qwen3")
    sid2 = _make(svc, name="Second")["system_id"]
    svc.link(sid2, "node", node_id, "owner.lan", role="built_on")
    assert svc.effective_risk_level(sid2).level == "medium"
    # unlinking removes the inherited level; nothing is stored
    for c in svc.get(sid2)["components"]:
        svc.unlink(sid2, c["component_id"], "owner.lan")
    assert svc.effective_risk_level(sid2).level == "unspecified"
    stored = adapters.state.get("ai_system", {"system_id": sid})
    assert stored["risk_level"] == "high" and stored["risk_level_source"] == "classifier"


def test_agent_not_in_inventory_falls_back_to_its_tier(
    svc: SystemService, adapters: Adapters
) -> None:
    add_agent(adapters, "lonely", risk_tier="high")
    sid = _make(svc)["system_id"]
    svc.link(sid, "agent", "lonely", "owner.lan")
    assert svc.effective_risk_level(sid).level == "high"


def test_link_rules(svc: SystemService, adapters: Adapters) -> None:
    add_agent(adapters, "a1")
    sid = _make(svc)["system_id"]
    with pytest.raises(NotFoundError, match="agent ghost"):
        svc.link(sid, "agent", "ghost", "owner.lan")
    with pytest.raises(NotFoundError, match="inventory node"):
        svc.link(sid, "node", "inv_nope", "owner.lan")
    with pytest.raises(SystemsError, match="ref_kind"):
        svc.link(sid, "model", "x", "owner.lan")
    with pytest.raises(SystemsError, match="role must be one of"):
        svc.link(sid, "agent", "a1", "owner.lan", role="owns")
    first = svc.link(sid, "agent", "a1", "owner.lan")
    again = svc.link(sid, "agent", "a1", "owner.lan")
    assert len(first["components"]) == len(again["components"]) == 1
    cid = first["components"][0]["component_id"]
    with pytest.raises(NotFoundError):
        svc.unlink(sid, "sc_nope", "owner.lan")
    svc.unlink(sid, cid, "owner.lan")
    with pytest.raises(NotFoundError):
        svc.unlink(sid, cid, "owner.lan")
    assert svc.link(sid, "agent", "a1", "owner.lan")["components"][0]["component_id"] == cid


# ------------------------------------------------------------------ scope


def test_scoped_roles_are_one_constant_that_with_all_roles_covers_every_role() -> None:
    assert SCOPED_ROLES == {"owner", "viewer", "operator"}
    assert ALL_ROLES == {"admin", "auditor", "reviewer", "approver"}
    assert SCOPED_ROLES | ALL_ROLES == set(rbac.ROLES) and not SCOPED_ROLES & ALL_ROLES


def test_scope_per_role(svc: SystemService, adapters: Adapters) -> None:
    mine = _make(svc)["system_id"]  # owner.lan, payments-team
    teamsys = svc.register(draft(name="Team sibling", owner_user="other.person"), "other.person")[
        "system_id"
    ]
    far = svc.register(
        draft(name="Far away", owner_user="far.person", owner_team="risk-team"), "far.person"
    )["system_id"]
    svc.add_member(far, "viewer.hoa", "technical_specialist", "far.person")
    # the five readers of everything
    for role in ("admin", "auditor", "reviewer", "approver"):
        assert svc.scope_for(person("someone", role)) is ALL
    # scoped roles: own, member of, and the team of a system they own
    for role in SCOPED_ROLES:
        got = svc.scope_for(person("owner.lan", role))
        assert got == {mine, teamsys}, role  # team sibling comes with the team
    assert svc.scope_for(person("viewer.hoa", "viewer")) == {far}
    assert svc.scope_for(person("nobody", "viewer")) == frozenset()
    assert svc.scope_for(person("nobody")) == frozenset()
    # one all-role among scoped roles wins
    assert svc.scope_for(person("owner.lan", "viewer", "reviewer")) is ALL
    # removing a member removes the access
    svc.remove_member(far, "viewer.hoa", "far.person")
    assert svc.scope_for(person("viewer.hoa", "viewer")) == frozenset()
    # list and get follow the scope
    names = {s["name"] for s in svc.list_systems(svc.scope_for(person("owner.lan", "owner")))}
    assert names == {"Payments - Assistant", "Team sibling"}
    assert len(svc.list_systems(ALL)) == 3
    assert svc.can_view(person("owner.lan", "owner"), mine)
    assert not svc.can_view(person("owner.lan", "owner"), far)


def test_agents_in_scope(svc: SystemService, adapters: Adapters) -> None:
    add_agent(adapters, "linked-mine")
    add_agent(adapters, "linked-far", team="risk-team", owner_user="far.p")
    add_agent(adapters, "free-mine", team="payments-team")
    add_agent(adapters, "free-far", team="risk-team", owner_user="far.p")
    add_agent(adapters, "linked-both", team="payments-team", owner_user="far.p")
    mine = _make(svc)["system_id"]
    far = svc.register(draft(name="Far", owner_user="far.p", owner_team="risk-team"), "far.p")[
        "system_id"
    ]
    svc.link(mine, "agent", "linked-mine", "owner.lan")
    svc.link(far, "agent", "linked-far", "far.p")
    svc.link(far, "agent", "linked-both", "far.p")  # linked to a system out of scope
    ids = {a["agent_id"] for a in svc.agents_in_scope(person("owner.lan", "owner"))}
    # linked-both has the team of the person but is linked to a system out of scope: hidden
    assert ids == {"linked-mine", "free-mine"}
    everyone = {a["agent_id"] for a in svc.agents_in_scope(person("x", "auditor"))}
    assert everyone == {"linked-mine", "linked-far", "free-mine", "free-far", "linked-both"}
    assert svc.agents_in_scope(person("nobody", "viewer")) == []


def test_list_filters(svc: SystemService) -> None:
    a = _make(svc)["system_id"]
    _make(svc, name="Other", owner_team="risk-team", system_type="decision")
    svc.update_fields(a, {"risk_level": "high", "status": "active"}, "owner.lan")
    assert [s["name"] for s in svc.list_systems(ALL, {"status": "active"})] == [
        "Payments - Assistant"
    ]
    assert [s["name"] for s in svc.list_systems(ALL, {"risk": "high"})] == ["Payments - Assistant"]
    assert [s["name"] for s in svc.list_systems(ALL, {"owner_team": "risk-team"})] == ["Other"]
    assert [s["name"] for s in svc.list_systems(ALL, {"q": "othe"})] == ["Other"]
    assert len(svc.list_systems(ALL, {"system_type": "decision"})) == 1
    for bad in ({"status": "x"}, {"risk": "x"}, {"nope": "x"}, {"lifecycle_stage": "x"}):
        with pytest.raises(SystemsError):
            svc.list_systems(ALL, bad)


# ------------------------------------------------------------------ chain


def _walk(value: Any) -> list[Any]:
    out = [value]
    if isinstance(value, dict):
        for v in value.values():
            out += _walk(v)
    elif isinstance(value, list):
        for v in value:
            out += _walk(v)
    return out


def test_every_change_writes_a_system_change_record(
    svc: SystemService, sink: ListSink, adapters: Adapters
) -> None:
    add_agent(adapters, "a1")
    s = _make(svc, purpose="Secret purpose text", name="Secret Name", business_owner="biz.tam")
    sid = s["system_id"]
    svc.update_fields(sid, {"risk_level": "low"}, "owner.lan")
    svc.add_member(sid, "rev.binh", "reviewer", "owner.lan")
    svc.remove_member(sid, "rev.binh", "owner.lan")
    cid = svc.link(sid, "agent", "a1", "owner.lan")["components"][0]["component_id"]
    svc.unlink(sid, cid, "owner.lan")
    svc.archive(sid, "owner.lan")
    recs = sink.of("system_change")
    assert [r["action"] for r in recs] == [
        "create",
        "update",
        "team_add",
        "team_remove",
        "link",
        "unlink",
        "archive",
    ]
    assert {ref for t, ref, _ in sink.records if t == "system_change"} == {f"system:{sid}"}
    text = json.dumps(recs, sort_keys=True)
    # no free text, no names, no user ids
    for secret in ("Secret", "owner.lan", "rev.binh", "biz.tam", "payments-team"):
        assert secret not in text, secret
    # canonical JSON friendly: only str, int, bool, None, list, dict; no floats
    assert not [v for r in recs for v in _walk(r) if isinstance(v, float)]
    last = recs[-1]
    assert last["status"] == "archived" and last["team_n"] == 2 and last["components_n"] == 0
    assert last["actor_ref"].startswith("act_") and len(last["row_hash"]) == 64
    assert recs[2]["member_ref"].startswith("act_") and recs[2]["team_role"] == "reviewer"
    assert recs[4]["component_id"] == cid and recs[4]["ref_kind"] == "agent"
    assert recs[0]["row_hash"] != recs[1]["row_hash"]

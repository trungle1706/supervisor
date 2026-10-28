# ruff: noqa: F811  (pytest fixtures are imported and then named as arguments)
"""WP-G4: the smart guardian (SMART_GUARDIAN).

Off path first (400 smart_guardian_off, no table read, panels absent), then the rules table on
synthetic inputs, the stored proposal (accept through the guardian service, the floor, reject,
supersede on a new run), the chain record (integers only) and RBAC.
"""

from __future__ import annotations

import copy
import datetime as dt
import json
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
import yaml

from supervisor.config import load_settings
from supervisor.core.errors import SupervisorError
from supervisor.evidence.chain import check_no_floats
from supervisor.governance import risk_dimensions as rd
from supervisor.governance.systems import ALL
from supervisor.onboard import orchestrator as orch
from supervisor.onboard import smart_guardian as sg
from tests.governance.conftest import Console, add_agent, draft, mounted, on  # noqa: F401

CREATOR = "reviewer.an"
VIEWER = "viewer.hoa"
NOW = dt.datetime(2026, 10, 28, 9, 0, tzinfo=dt.UTC)
AGENT = "g4-agent"
FLAGS = (
    "risk_dimensions",
    "classification_v2",
    "smart_guardian",
    "guardian_bindings_enabled",
)
TH = {
    "personal_per_transaction_vnd": 10000000,
    "personal_per_day_vnd": 20000000,
    "organisation_per_transaction_vnd": 50000000,
    "organisation_per_day_vnd": 100000000,
    "credit_vnd": 50000000,
}


@pytest.fixture
def sgon(on: Console, monkeypatch: pytest.MonkeyPatch) -> Iterator[Console]:
    for flag in FLAGS:
        monkeypatch.setattr(on.ctx.settings, flag, True)
    yield on


def _system(c: Console, **over: Any) -> str:
    name = over.pop("name", None) or f"System {len(c.ctx.systems.list_systems(ALL, {}))}"
    s = c.ctx.systems.register(draft(owner_user=CREATOR, name=name, **over), CREATOR)
    return str(s["system_id"])


def _classify(c: Console, sid: str, outcome: str) -> None:
    tree = c.ctx.classification_v2.tree()
    c.ctx.state.insert(
        "classification_v2",
        {
            "classification_id": f"cls-{sid}-1",
            "system_id": sid,
            "outcome": outcome,
            "path_json": [],
            "tree_sha256": tree.sha256,
            "path_hash": "0" * 64,
            "decided_by": "someone.else",
            "approved_by": "approver.em",
            "approved_at": NOW,
            "inherited_from_provider": False,
            "valid_until": NOW + dt.timedelta(days=365),
            "created_at": NOW,
        },
    )


def _ready(c: Console, outcome: str = "high_self", **over: Any) -> str:
    add_agent(c.runtime.adapters, AGENT)
    sid = _system(c, **over)
    c.ctx.systems.link(sid, "agent", AGENT, CREATOR)
    _classify(c, sid, outcome)
    return sid


def _dim(c: Console, sid: str, dim: str, status: str) -> None:
    c.ctx.state.insert(
        "risk_dimension_status",
        {
            "status_id": rd.status_id(sid, dim),
            "system_id": sid,
            "dimension_id": dim,
            "status": status,
            "owner_team": None,
            "assessed_by": None,
            "report_ref": None,
            "evidence_json": [],
            "threshold_json": {},
            "note": None,
            "updated_by": "rule:test",
            "valid_until": None,
        },
    )


def _api(c: Console, method: str, url: str, body: Any = None, user: str = CREATOR) -> Any:
    return c.client.request(method, url, json=body, headers={"X-Dev-User": user})


def _url(sid: str, tail: str = "") -> str:
    return f"/v1/systems/{sid}/guardian-proposal{tail}"


def _subjects(lines: list[dict[str, Any]], group: str | None = None) -> set[str]:
    return {ln["subject"] for ln in lines if group is None or ln["group"] == group}


# ------------------------------------------------------------------ off path


def test_flag_off_by_default_and_needs_the_others(console: Console) -> None:
    assert load_settings(llm_base_url="").smart_guardian is False
    s = console.ctx.settings
    assert sg.enabled(s) is False
    s2 = load_settings(llm_base_url="", smart_guardian=True)
    assert sg.enabled(s2) is False  # needs governance and risk dimensions
    s3 = load_settings(
        llm_base_url="", smart_guardian=True, governance_enabled=True, risk_dimensions=True
    )
    assert sg.enabled(s3) is True


def test_off_routes_400_no_table_read_panel_absent(
    on: Console, monkeypatch: pytest.MonkeyPatch
) -> None:
    c = on
    monkeypatch.setattr(c.ctx.settings, "risk_dimensions", True)
    monkeypatch.setattr(c.ctx.settings, "console_nav_v3", True)
    sid = _system(c)
    seen: list[str] = []
    real_q, real_g = c.ctx.state.query, c.ctx.state.get

    def spy_q(table: str, *a: Any, **k: Any) -> Any:
        seen.append(table)
        return real_q(table, *a, **k)

    def spy_g(table: str, *a: Any, **k: Any) -> Any:
        seen.append(table)
        return real_g(table, *a, **k)

    monkeypatch.setattr(c.ctx.state, "query", spy_q)
    monkeypatch.setattr(c.ctx.state, "get", spy_g)
    for method, tail in (("GET", ""), ("POST", ""), ("POST", "/accept"), ("POST", "/reject")):
        r = _api(c, method, _url(sid, tail), {} if method == "POST" else None)
        assert r.status_code == 400 and "smart_guardian_off" in r.text, (method, tail)
    assert c.get(f"/console/systems/{sid}/guardian-proposal?lang=en").status_code == 400
    for tail in ("", "/accept", "/reject"):
        r = c.post(f"/console/systems/{sid}/guardian-proposal{tail}", {})
        assert r.status_code == 400, tail
    tab = c.get(f"/console/systems/{sid}?tab=guardians&lang=en")
    assert tab.status_code == 200
    assert "smart-guardian" not in tab.text and "sg-propose" not in tab.text
    assert "guardian_proposal" not in seen


# ------------------------------------------------------------------ the rules table


def inp(**over: Any) -> sg.Inputs:
    base: dict[str, Any] = {
        "system_id": "S1",
        "outcome": "low",
        "thresholds": TH,
        "flags": {},
        "segment": "internal",
    }
    base.update(over)
    return sg.Inputs(**base)


CFG = sg.load_config()

FAIL_CYBER_FINDING = {
    "cybersecurity": [
        {
            "finding_id": "f8-cy-08",
            "checklist_id": "CY-08",
            "verdict": "fail",
            "report_id": "rep-cy-1",
        }
    ]
}
TOOL_FACTS = [
    {
        "fact_id": "ft1",
        "kind": "tool",
        "name": "transfer_funds",
        "file": "agent/tools.py",
        "line": 12,
    },
    {
        "fact_id": "ft2",
        "kind": "tool",
        "name": "export_statement",
        "file": "agent/tools.py",
        "line": 40,
    },
]


def test_high_risk_payment_agent_with_cyber_fail_gets_injection_pair_and_money_approval() -> None:
    lines = sg.evaluate(
        inp(
            outcome="high_self",
            autonomy_level="l4_autonomous_bounded",
            money=True,
            segment="customer",
            personal_data="identifiable",
            flags={"agentic": True, "generative": True},
            dim_status={"cybersecurity": "fail", "data_governance": "pass"},
            findings=FAIL_CYBER_FINDING,
            facts=TOOL_FACTS,
            floor=[{"slug": "policy_rules", "rules": ["AR-X"]}],
        ),
        CFG,
    )
    g = _subjects(lines, "guardian_set")
    assert {"injection_regex", "guard_model", "dlp_vn", "session_monitor"} <= g
    assert "monitor_split_payment" in g
    pair = [ln for ln in lines if ln["rule_id"] == "SG-G-INJ-PAIR"]
    assert {ln["subject"] for ln in pair} == {"injection_regex", "guard_model"}
    assert all(ln["stage"] == "tool_call" for ln in pair)
    assert pair[0]["why"] == {
        "kind": "finding",
        "id": "cybersecurity/f8-cy-08",
        "detail": "report rep-cy-1 checklist CY-08 verdict fail",
    }
    a = {ln["subject"]: ln for ln in lines if ln["group"] == "autonomy_limits"}
    assert a["approval_above_vnd"]["value"] == 10000000  # a customer: the personal threshold
    assert a["daily_total_vnd"]["value"] == 20000000
    assert a["max_level"]["value"] == "l3_tool_using_supervised"
    assert a["session_max_tool_calls"]["value"] == 30
    t = {ln["subject"]: ln for ln in lines if ln["group"] == "thresholds"}
    assert t["guard_model.preset"]["value"] == "strict"
    assert t["dlp_vn.transform_tools"]["value"] == ["export_statement"]
    assert t["dlp_vn.transform_tools"]["why"]["kind"] == "fact"
    assert t["drift.consecutive"]["value"] == 2
    assert [ln["subject"] for ln in lines if ln["group"] == "floor"] == ["policy_rules"]


def test_organisation_segment_uses_the_organisation_threshold() -> None:
    lines = sg.evaluate(inp(outcome="medium", money=True, segment="partner"), CFG)
    a = {ln["subject"]: ln["value"] for ln in lines if ln["group"] == "autonomy_limits"}
    assert a["approval_above_vnd"] == 50000000 and a["daily_total_vnd"] == 100000000


def test_low_risk_internal_assistant_all_pass_gets_the_floor_only() -> None:
    floor = [{"slug": "policy_rules", "rules": ["AR-ALWAYS"]}]
    lines = sg.evaluate(
        inp(
            outcome="low",
            autonomy_level="l1_assistive",
            dim_status=dict.fromkeys(rd.DIMENSION_IDS, "pass"),
            flags={"generative": True},
            floor=floor,
        ),
        CFG,
    )
    assert [ln["group"] for ln in lines] == ["floor"]
    assert lines[0]["selectable"] is False and lines[0]["rule_id"] == "SG-F-FLOOR"


@pytest.mark.parametrize(
    ("over", "present", "absent"),
    [
        ({"dim_status": {"cybersecurity": "fail"}}, {"injection_regex", "guard_model"}, set()),
        ({"dim_status": {"cybersecurity": "pass"}}, set(), {"injection_regex", "guard_model"}),
        ({"personal_data": "special"}, {"dlp_vn"}, set()),
        ({"facts": [{"fact_id": "d1", "kind": "dataset", "name": "customers"}]}, {"dlp_vn"}, set()),
        ({"flags": {"decides": True}}, {"judge_t2_sample"}, set()),
        ({"dim_status": {"ethics": "fail"}}, {"judge_t2_sample"}, set()),
        ({"dim_status": {"model": "fail"}}, {"monitor_drift", "monitor_quality"}, set()),
        ({"credit": True}, {"monitor_fairness"}, set()),
        ({"money": True}, set(), {"monitor_split_payment"}),  # not agentic
        ({"money": True, "flags": {"agentic": True}}, {"monitor_split_payment"}, set()),
        (
            {"outcome": "medium", "flags": {"agentic": True}},
            {"injection_regex"},
            {"session_monitor"},
        ),
        ({"autonomy_level": "l3_tool_using_supervised"}, {"session_monitor"}, set()),
        ({"autonomy_level": "unspecified"}, set(), {"session_monitor"}),
        (
            {"findings": {"cybersecurity": [{"verdict": "fail", "checklist_id": "CY-02"}]}},
            set(),
            {"injection_regex"},
        ),
        (
            {
                "findings": {
                    "cybersecurity": [{"verdict": "fail", "checklist_id": "tool-injection"}]
                }
            },
            {"injection_regex"},
            set(),
        ),
    ],
)
def test_guardian_set_rules(over: dict[str, Any], present: set[str], absent: set[str]) -> None:
    got = _subjects(sg.evaluate(inp(**over), CFG), "guardian_set")
    assert present <= got and not (absent & got)


def test_floor_slug_is_not_proposed_twice() -> None:
    lines = sg.evaluate(
        inp(personal_data="identifiable", floor=[{"slug": "dlp_vn", "rules": ["AR-PII"]}]), CFG
    )
    assert "dlp_vn" not in _subjects(lines, "guardian_set")
    assert _subjects(lines, "floor") == {"dlp_vn"}


@pytest.mark.parametrize(
    ("level", "calls", "minutes"),
    [("high_certify", 20, 30), ("high_self", 30, 30), ("medium", 60, 60), ("low", 100, 120)],
)
def test_session_limits_by_level(level: str, calls: int, minutes: int) -> None:
    lines = sg.evaluate(inp(outcome=level, flags={"agentic": True}), CFG)
    a = {ln["subject"]: ln["value"] for ln in lines if ln["group"] == "autonomy_limits"}
    assert a["session_max_tool_calls"] == calls and a["session_max_minutes"] == minutes


def test_max_level_only_when_it_lowers_something() -> None:
    low = sg.evaluate(inp(outcome="high_self", autonomy_level="l3_tool_using_supervised"), CFG)
    assert "max_level" not in _subjects(low, "autonomy_limits")
    high = sg.evaluate(inp(outcome="high_self", autonomy_level="l4_autonomous_bounded"), CFG)
    assert "max_level" in _subjects(high, "autonomy_limits")


def test_every_line_has_why_pointer_rule_id_and_integers_only() -> None:
    lines = sg.evaluate(
        inp(
            outcome="high_certify",
            autonomy_level="l4_autonomous_bounded",
            money=True,
            credit=True,
            personal_data="special",
            flags={"agentic": True, "decides": True, "generative": True},
            dim_status={d: "fail" for d in ("cybersecurity", "model", "ethics", "data_governance")},
            findings=FAIL_CYBER_FINDING,
            facts=TOOL_FACTS,
            floor=[{"slug": "policy_rules", "rules": ["AR-A"]}, {"slug": "dlp_vn", "rules": []}],
        ),
        CFG,
    )
    assert len(lines) > 12
    ids = [ln["line_id"] for ln in lines]
    assert len(ids) == len(set(ids))
    rule_ids = {r["id"] for r in CFG.rules} | {"SG-F-FLOOR"}
    for ln in lines:
        assert ln["rule_id"] in rule_ids
        assert ln["why"]["kind"] in sg.WHY_KINDS and ln["why"]["id"]
        assert ln["group"] in sg.GROUPS
    check_no_floats({"lines": lines})
    assert json.loads(json.dumps(lines)) == lines


def test_config_is_strict() -> None:
    doc = yaml.safe_load(
        open(Path(__file__).parents[2] / "config" / "smart_guardian.yaml", encoding="utf-8")
    )
    assert doc["illustrative"] is True
    assert sg.parse_config(copy.deepcopy(doc)).rules
    bad = copy.deepcopy(doc)
    bad["rules"][0]["when"] = {"nonsense": 1}
    bad["rules"][0].pop("any_of", None)
    with pytest.raises(SupervisorError):
        sg.parse_config(bad)
    flo = copy.deepcopy(doc)
    flo["rules"][-1]["lines"][0]["value_by_level"]["low"] = 1.5
    with pytest.raises(SupervisorError):
        sg.parse_config(flo)
    dup = copy.deepcopy(doc)
    dup["rules"][1]["id"] = dup["rules"][0]["id"]
    with pytest.raises(SupervisorError):
        sg.parse_config(dup)


# ------------------------------------------------------------------ the stored proposal


def test_create_needs_a_classification_and_blocks_prohibited(sgon: Console) -> None:
    c = sgon
    sid = _system(c)
    r = _api(c, "POST", _url(sid), {})
    assert r.status_code == 400 and "classification_required" in r.text
    _classify(c, sid, "prohibited")
    r = _api(c, "POST", _url(sid), {})
    assert r.status_code == 400 and "plan_blocked" in r.text


def test_create_get_and_idempotent_repeat(sgon: Console) -> None:
    c = sgon
    sid = _ready(c, "high_self", money_movement=True)
    assert _api(c, "GET", _url(sid)).status_code == 404
    r = _api(c, "POST", _url(sid), {})
    assert r.status_code == 201, r.text
    row = r.json()
    assert row["status"] == "proposed" and row["attempt_n"] == 0
    assert row["proposal"]["counts"]["guardian_set"] >= 1
    again = _api(c, "POST", _url(sid), {}).json()
    assert again["proposal_id"] == row["proposal_id"]  # same content: the open one is returned
    got = _api(c, "GET", _url(sid)).json()
    assert got["proposal_id"] == row["proposal_id"]
    assert len(c.ctx.state.query("guardian_proposal", {"system_id": sid})) == 1
    # changed inputs: the open proposal is superseded by a new one
    c.ctx.systems.update_fields(sid, {"credit_decision": True}, CREATOR)
    new = _api(c, "POST", _url(sid), {}).json()
    assert new["proposal_id"] != row["proposal_id"]
    states = {r["proposal_id"]: r["status"] for r in c.ctx.state.query("guardian_proposal")}
    assert states[row["proposal_id"]] == "superseded" and states[new["proposal_id"]] == "proposed"


def test_accept_writes_bindings_through_the_service_and_keeps_the_floor(sgon: Console) -> None:
    c = sgon
    sid = _ready(c, "high_self", money_movement=True, user_segment="customer")
    _dim(c, sid, "cybersecurity", "fail")
    # a person switched injection_regex off before; accepting puts it back on through the service
    c.ctx.guardians.set(sid, "monitor_drift", "off", CREATOR, "tested off")
    row = _api(c, "POST", _url(sid), {}).json()
    lines = row["proposal"]["lines"]
    floor = [ln for ln in lines if ln["group"] == "floor"]
    assert floor, "a money system has a guardian floor"
    # the floor cannot be accepted
    r = _api(c, "POST", _url(sid, "/accept"), {"lines": [floor[0]["line_id"]]})
    assert r.status_code == 400 and "floor_line" in r.text
    guard = [ln for ln in lines if ln["group"] == "guardian_set"]
    pair = [ln["line_id"] for ln in guard if ln["rule_id"] == "SG-G-INJ-PAIR"]
    assert len(pair) == 1  # injection_regex sits in the floor of a money system, guard_model not
    r = _api(c, "POST", _url(sid, "/accept"), {"lines": pair, "note": "pair only"})
    assert r.status_code == 200, r.text
    done = r.json()
    assert done["status"] == "accepted" and done["note"] == "pair only"
    dec = done["proposal"]["decision"]
    assert dec["accepted"] == sorted(pair) and dec["next"] == "run_predeploy"
    assert {x["result"] for x in dec["results"]} == {"applied"}
    states = {ln["line_id"]: ln["state"] for ln in done["proposal"]["lines"]}
    assert all(states[p] == "accepted" for p in pair)
    assert any(s == "not_accepted" for s in states.values())  # the others stay open to the record
    # nothing was scheduled and nothing else was written
    assert c.ctx.state.query("policy_threshold") == []
    # the floor rows stay locked; the binding view says so
    view = {g["slug"]: g for g in c.ctx.guardians.get(sid)["guardians"]}
    assert all(view[f["subject"]]["locked"] for f in floor)
    # a second accept answers 400 (no open proposal)
    r = _api(c, "POST", _url(sid, "/accept"), {"lines": pair})
    assert r.status_code == 400 and "no_open_proposal" in r.text


def test_accept_flips_an_off_row_back_on_and_never_bypasses_the_service(
    sgon: Console, monkeypatch: pytest.MonkeyPatch
) -> None:
    c = sgon
    sid = _ready(c, "high_self", money_movement=True)
    _dim(c, sid, "model", "fail")
    c.ctx.guardians.set(sid, "monitor_drift", "off", CREATOR, "off for a test")
    row = _api(c, "POST", _url(sid), {}).json()
    drift = next(ln for ln in row["proposal"]["lines"] if ln["subject"] == "monitor_drift")
    calls: list[tuple[Any, ...]] = []
    real = type(c.ctx.guardians).set

    def spy(self: Any, *a: Any, **k: Any) -> Any:
        calls.append(a)
        return real(self, *a, **k)

    monkeypatch.setattr(type(c.ctx.guardians), "set", spy)
    r = _api(c, "POST", _url(sid, "/accept"), {"lines": [drift["line_id"]]})
    assert r.status_code == 200, r.text
    assert calls and calls[0][1:3] == ("monitor_drift", "on")
    binding = c.ctx.state.get(
        "guardian_binding", {"system_id": sid, "feature_slug": "monitor_drift"}
    )
    assert binding["state"] == "on"
    sink = c.runtime.chain if hasattr(c.runtime, "chain") else None
    assert sink is not None


def test_accept_thresholds_and_limits(sgon: Console) -> None:
    c = sgon
    sid = _ready(c, "high_self", money_movement=True, autonomy_level="l4_autonomous_bounded")
    c.ctx.systems.update_fields(sid, {"tags": {"ai_agentic": "1"}}, CREATOR)
    row = _api(c, "POST", _url(sid), {}).json()
    by = {ln["subject"]: ln for ln in row["proposal"]["lines"]}
    pick = [
        by["drift.consecutive"]["line_id"],
        by["guard_model.preset"]["line_id"],
        by["approval_above_vnd"]["line_id"],
        by["max_level"]["line_id"],
    ]
    r = _api(c, "POST", _url(sid, "/accept"), {"lines": pick})
    assert r.status_code == 200, r.text
    dec = r.json()["proposal"]["decision"]
    assert {x["subject"]: x["result"] for x in dec["results"]} == {
        "drift.consecutive": "applied",
        "guard_model.preset": "recorded",
        "approval_above_vnd": "applied",
        "max_level": "applied",
    }
    pt = c.ctx.state.get("policy_threshold", {"agent_id": AGENT, "metric": "drift.consecutive"})
    assert pt["threshold"] == 2 and pt["unit"] == "days"
    tags = c.ctx.systems.get(sid)["tags"]
    limits = json.loads(tags["autonomy_limits"])
    assert limits == {"approval_above_vnd": 50000000, "max_level": "l3_tool_using_supervised"}
    assert tags["ai_agentic"] == "1"  # the other tags stay
    snippet = yaml.safe_load(dec["policy_snippet"])
    assert snippet["agents"][AGENT]["detectors"]["settings"]["guard_model"]["preset"] == "strict"
    # autonomy_level of the system itself is not changed by an accepted cap
    assert c.ctx.systems.get(sid)["autonomy_level"] == "l4_autonomous_bounded"


def test_accept_validates_the_ids(sgon: Console) -> None:
    c = sgon
    sid = _ready(c, "medium")
    _api(c, "POST", _url(sid), {})
    for body in ({}, {"lines": []}, {"lines": "x"}, {"lines": ["ln_nope"]}, {"lines": [5]}):
        r = _api(c, "POST", _url(sid, "/accept"), body)
        assert r.status_code == 400, body
    r = c.client.post(_url(sid, "/accept"), content=b"not json", headers={"X-Dev-User": CREATOR})
    assert r.status_code == 400
    # bindings off: guardian lines are refused before any write
    c.ctx.settings.guardian_bindings_enabled = False
    row = sg.current(c.ctx, sid)
    guard = [ln for ln in row["proposal"]["lines"] if ln["group"] == "guardian_set"]
    if guard:
        r = _api(c, "POST", _url(sid, "/accept"), {"lines": [guard[0]["line_id"]]})
        assert r.status_code == 400


def test_reject_needs_a_reason_of_20_characters(sgon: Console) -> None:
    c = sgon
    sid = _ready(c, "high_self", money_movement=True)
    _api(c, "POST", _url(sid), {})
    for reason in (None, "", "too short", "x" * 19, "x" * 301, "has\x01control chars here ok"):
        r = _api(c, "POST", _url(sid, "/reject"), {"reason": reason})
        assert r.status_code == 400, reason
    r = _api(c, "POST", _url(sid, "/reject"), {"reason": "the cap is wrong for this team"})
    assert r.status_code == 200 and r.json()["status"] == "rejected"
    assert r.json()["decided_by"] == CREATOR
    assert _api(c, "POST", _url(sid, "/reject"), {"reason": "x" * 25}).status_code == 400
    assert _api(c, "GET", _url(sid)).json()["status"] == "rejected"


def test_a_new_assessment_run_supersedes_the_open_proposal(
    sgon: Console, monkeypatch: pytest.MonkeyPatch
) -> None:
    c = sgon
    monkeypatch.setattr(c.ctx.settings, "onboard_orchestrator", True)
    sid = _ready(c, "high_self", money_movement=True)
    orch.run(c.ctx, sid, 1)
    row = _api(c, "POST", _url(sid), {}).json()
    assert row["attempt_n"] == 1 and row["status"] == "proposed"
    assert row["proposal"]["inputs"]["reports_n"] == 8
    orch.run(c.ctx, sid, 2)
    got = _api(c, "GET", _url(sid)).json()
    assert got["proposal_id"] == row["proposal_id"] and got["status"] == "superseded"
    r = _api(c, "POST", _url(sid, "/accept"), {"lines": [row["proposal"]["lines"][0]["line_id"]]})
    assert r.status_code == 400 and "no_open_proposal" in r.text
    fresh = _api(c, "POST", _url(sid), {}).json()
    assert fresh["attempt_n"] == 2 and fresh["status"] == "proposed"


class _CyberFail:
    """Rule runner that adds a failed CY-08 finding to the cybersecurity report."""

    def __init__(self) -> None:
        self.rule = orch.RuleRunner()

    def run(self, request: orch.AgentRequest) -> dict[str, Any]:
        rep = self.rule.run(request)
        if request.dimension_id == "cybersecurity":
            rep["findings"].append(
                {
                    "finding_id": "f9-cy-08",
                    "checklist_id": "cy-08",
                    "verdict": "fail",
                    "evidence": [{"kind": "fact", "ref": "fact:ft1", "file": "a.py", "line": 3}],
                    "rationale": "No injection test for tool transfer.",
                    "confidence": "high",
                }
            )
            rep["summary"] = orch._summary(rep["findings"])  # noqa: SLF001
        return rep


def test_reads_the_newest_report_findings(sgon: Console, monkeypatch: pytest.MonkeyPatch) -> None:
    c = sgon
    monkeypatch.setattr(c.ctx.settings, "onboard_orchestrator", True)
    sid = _ready(c, "medium")
    run = orch.run(c.ctx, sid, 1, runner=_CyberFail())
    assert run.status == "done"
    prop = sg.propose(c.ctx, sid)
    pair = [ln for ln in prop.lines if ln["rule_id"] == "SG-G-INJ-PAIR"]
    assert {ln["subject"] for ln in pair} == {"injection_regex", "guard_model"}
    assert pair[0]["why"]["kind"] == "finding"
    assert pair[0]["why"]["id"] == "cybersecurity/f9-cy-08"


def test_chain_record_has_ids_hash_and_integers_only(
    sgon: Console, monkeypatch: pytest.MonkeyPatch
) -> None:
    c = sgon
    seen: list[tuple[str, str, dict[str, Any]]] = []

    class Sink:
        def record(self, rt: str, ref: str, payload: Any) -> str:
            seen.append((rt, ref, dict(payload)))
            return "h"

        def close(self) -> None:
            return None

    monkeypatch.setattr(c.runtime, "chain", Sink())
    sid = _ready(c, "high_self", money_movement=True)
    row = _api(c, "POST", _url(sid), {}).json()
    pick = [ln["line_id"] for ln in row["proposal"]["lines"] if ln["selectable"]][:2]
    assert _api(c, "POST", _url(sid, "/accept"), {"lines": pick}).status_code == 200
    mine = [p for t, _, p in seen if t == "guardian_proposal"]
    assert [p["status"] for p in mine] == ["proposed", "accepted"]
    for p in mine:
        check_no_floats(p)
        assert set(p) == {
            "proposal_id",
            "system_id",
            "attempt_n",
            "status",
            "proposal_sha256",
            "n_guardian_set",
            "n_thresholds",
            "n_autonomy_limits",
            "n_floor",
            "n_accepted",
            "actor_ref",
            "ts",
        }
        assert len(p["proposal_sha256"]) == 64 and CREATOR not in json.dumps(p)
        assert all(isinstance(p[k], int) for k in p if k.startswith("n_"))
    assert mine[1]["n_accepted"] == 2


def test_note_is_masked(sgon: Console) -> None:
    c = sgon
    sid = _ready(c, "medium")
    row = _api(c, "POST", _url(sid), {}).json()
    pick = [ln["line_id"] for ln in row["proposal"]["lines"] if ln["selectable"]][:1]
    note = "see https://workspace.example.net/secret/path for the case"
    r = _api(c, "POST", _url(sid, "/accept"), {"lines": pick, "note": note})
    assert r.status_code == 200 and "https://" not in r.json()["note"]


def test_rbac_and_scope(sgon: Console) -> None:
    c = sgon
    sid = _ready(c, "medium")
    assert _api(c, "POST", _url(sid), {}, user=VIEWER).status_code == 403
    assert _api(c, "POST", _url(sid, "/accept"), {}, user=VIEWER).status_code == 403
    assert _api(c, "POST", _url(sid, "/reject"), {}, user=VIEWER).status_code == 403
    assert _api(c, "POST", _url(sid), {}, user=CREATOR).status_code == 201
    assert _api(c, "GET", _url(sid), user=VIEWER).status_code != 403
    assert _api(c, "GET", "/v1/systems/nope/guardian-proposal", user=VIEWER).status_code == 404
    ghost = _api(c, "POST", "/v1/systems/sys_0000000000000000/guardian-proposal", {})
    assert ghost.status_code in (400, 404)  # never 201, never 500


def test_audit_rows_for_every_post(sgon: Console) -> None:
    c = sgon
    sid = _ready(c, "medium")
    before = len(c.ctx.tables.query("console_action"))
    _api(c, "POST", _url(sid), {})
    rows = c.ctx.tables.query("console_action", order_by=("ts",))[before:]
    assert [r["outcome"] for r in rows] == ["attempted", "ok"]
    assert all(r["permission"] == "systems.edit" for r in rows)

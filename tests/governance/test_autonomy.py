"""WP-G2 autonomy level: the enum, the gte ordering, the three starter rules and the Decision 33
interaction."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from supervisor.adapters.factory import Adapters
from supervisor.config import load_settings
from supervisor.governance import model as gm
from supervisor.governance import rules as R
from supervisor.governance.classification import ClassificationService
from supervisor.governance.conditions import RulesError
from supervisor.governance.model import SystemsError
from supervisor.governance.rules_service import RulesService, build_catalogue
from supervisor.governance.systems import SystemService

from .conftest import draft, person

STARTER = Path(__file__).resolve().parents[2] / "config" / "assignment_rules.yaml"
L = gm.AUTONOMY_LEVELS


def test_enum_order_and_validation(svc: SystemService) -> None:
    assert L == (
        "unspecified",
        "l0_rule_based",
        "l1_assistive",
        "l2_workflow_step",
        "l3_tool_using_supervised",
        "l4_autonomous_bounded",
        "l5_self_directed",
    )
    assert [gm.autonomy_rank(x) for x in L] == [0, 1, 2, 3, 4, 5, 6]
    assert gm.autonomy_rank(None) == 0
    s = svc.register(draft(autonomy_level="l2_workflow_step"), "owner.lan")
    assert s["autonomy_level"] == "l2_workflow_step"
    for lv in L:
        assert (
            svc.update_fields(s["system_id"], {"autonomy_level": lv}, "owner.lan")["autonomy_level"]
            == lv
        )
    with pytest.raises(SystemsError, match="autonomy_level must be one of"):
        svc.update_fields(s["system_id"], {"autonomy_level": "l9"}, "owner.lan")
    with pytest.raises(SystemsError, match="autonomy_level"):
        svc.register(draft(name="Other", autonomy_level="robot"), "owner.lan")
    plain = {k: v for k, v in draft(name="Third").items() if k != "autonomy_level"}
    assert svc.register(plain, "owner.lan")["autonomy_level"] == "unspecified"


def _facts(level: str | None) -> dict[str, Any]:
    return R.facts_of(
        {"status": "draft", "autonomy_level": level, "money_movement": False}, "low", {}, ()
    )


def test_gte_ordering_and_unspecified_never_matches() -> None:
    cat = build_catalogue(load_settings(sql_backend="sqlite", llm_base_url=""))
    for i, gate in enumerate(L[1:], start=1):
        rs = R.RuleSet(
            R.parse_rules(
                [
                    {
                        "id": "T",
                        "when": {"field": "autonomy_level", "gte": gate},
                        "assign": {"controls": ["CTL-X"]},
                    }
                ]
            ),
            "0" * 64,
        )
        for j, lv in enumerate(L):
            fired = bool(R.evaluate(rs, _facts(lv), cat).fired)
            assert fired == (j >= i), (gate, lv)
        assert not R.evaluate(rs, _facts(None), cat).fired  # a row from before WP-G2
    with pytest.raises(RulesError, match="match everything"):
        R.parse_rules(
            [
                {
                    "id": "T",
                    "when": {"field": "autonomy_level", "gte": "unspecified"},
                    "assign": {"controls": ["CTL-X"]},
                }
            ]
        )


def test_starter_rules_for_l3_l4_l5() -> None:
    rs = R.load_rules(STARTER)
    cat = build_catalogue(load_settings(sql_backend="sqlite", llm_base_url=""))
    assert R.problems(rs, cat) == []

    def run(level: str) -> R.Evaluation:
        return R.evaluate(rs, _facts(level), cat)

    def ids(ev: R.Evaluation, kind: str) -> set[str]:
        return {a.ref_id for a in ev.of(kind)}

    assert not [r for r in run("l2_workflow_step").fired if r.startswith("AR-AUTONOMY")]
    l3 = run("l3_tool_using_supervised")
    assert [r for r in l3.fired if r.startswith("AR-AUTONOMY")] == ["AR-AUTONOMY-L3"]
    assert ids(l3, "guardian") == {"policy_rules", "dlp_vn"}
    l4 = run("l4_autonomous_bounded")
    assert [r for r in l4.fired if r.startswith("AR-AUTONOMY")] == [
        "AR-AUTONOMY-L3",
        "AR-AUTONOMY-L4",
    ]
    assert ids(l4, "guardian") == {"policy_rules", "dlp_vn", "session_monitor"}
    assert "OPS-RESUME-2P" in ids(l4, "task") and "CTL-BANK-PAUSETEST" in ids(l4, "control")
    l5 = run("l5_self_directed")
    assert [r for r in l5.fired if r.startswith("AR-AUTONOMY")] == [
        "AR-AUTONOMY-L3",
        "AR-AUTONOMY-L4",
        "AR-AUTONOMY-L5",
    ]
    assert ids(l5, "risk") == {"RSK-SHR-003"}
    assert {"INI-REGISTER", "INI-D33"} <= ids(l5, "task")
    # the explanation shows the level that fired
    text = "\n".join(R.explain_lines(rs, l4))
    assert "rule AR-AUTONOMY-L4: FIRED" in text
    assert "autonomy_level gte 'l4_autonomous_bounded'  seen 'l4_autonomous_bounded'" in text
    assert "autonomy_level = l4_autonomous_bounded" in text


def test_assigned_only_task_is_not_in_sizing() -> None:
    from supervisor.tasks.model import CLASSES, LEVELS, load_config, plan

    cfg = load_config(Path(STARTER).parents[0] / "tasks.yaml")
    tpl = cfg.by_id()["OPS-RESUME-2P"]
    assert tpl.assigned_only
    for cls in CLASSES:
        for band in LEVELS:
            assert all(
                x.template.id != "OPS-RESUME-2P" for xs in plan(cfg, cls, band).values() for x in xs
            )


def test_rules_run_on_the_system_and_the_floor_is_the_gate_features(
    gsvc: SystemService, gadapters: Adapters
) -> None:
    s = gsvc.register(draft(autonomy_level="l4_autonomous_bounded"), "owner.lan")
    floor = {
        f["slug"] for f in RulesService.from_adapters(gadapters).guardian_floor(s["system_id"])
    }
    assert floor >= {"policy_rules", "dlp_vn", "session_monitor"}
    gsvc.update_fields(s["system_id"], {"autonomy_level": "l1_assistive"}, "owner.lan")
    assert "session_monitor" not in {
        f["slug"] for f in RulesService.from_adapters(gadapters).guardian_floor(s["system_id"])
    }


# ---- Decision 33 interaction ------------------------------------------------------------------


def _c(a: Adapters) -> ClassificationService:
    return ClassificationService.from_adapters(a)


def test_apply_is_blocked_while_the_level_is_unspecified(
    gsvc: SystemService, gadapters: Adapters
) -> None:
    s = gsvc.register(draft(money_movement=True, autonomy_level="unspecified"), "owner.lan")
    c = _c(gadapters)
    c.draft(s["system_id"], "owner.lan")
    with pytest.raises(SystemsError, match="autonomy_level is not set"):
        c.apply(s["system_id"], person("rev.an", "admin"))
    gsvc.update_fields(s["system_id"], {"autonomy_level": "l3_tool_using_supervised"}, "owner.lan")
    c.apply(s["system_id"], person("rev.an", "admin"))
    assert gsvc.get(s["system_id"])["decision33_class"] == "high_risk"


@pytest.mark.parametrize("level", ["l4_autonomous_bounded", "l5_self_directed"])
@pytest.mark.parametrize("field", ["money_movement", "credit_decision"])
def test_l4_l5_with_money_or_credit_and_no_pre_approval_is_high_risk(
    gsvc: SystemService, gadapters: Adapters, level: str, field: str
) -> None:
    s = gsvc.register(
        draft(autonomy_level=level, human_control="post_review", **{field: True}), "owner.lan"
    )
    out = _c(gadapters).draft(s["system_id"], "owner.lan")
    assert out["outcome"] == "high_risk"


def test_the_level_does_not_lower_a_class(gsvc: SystemService, gadapters: Adapters) -> None:
    for i, level in enumerate(("l0_rule_based", "l1_assistive", "l5_self_directed")):
        s = gsvc.register(
            draft(name=f"S{i}", autonomy_level=level, money_movement=True, human_control="none"),
            "owner.lan",
        )
        assert _c(gadapters).draft(s["system_id"], "owner.lan")["outcome"] == "high_risk"
    p = gsvc.register(
        draft(
            name="P",
            autonomy_level="l4_autonomous_bounded",
            money_movement=True,
            human_control="pre_approval",
        ),
        "owner.lan",
    )
    assert _c(gadapters).draft(p["system_id"], "owner.lan")["outcome"] == "unclassified"


def test_l5_sets_the_risk_floor_to_prohibited(gsvc: SystemService, gadapters: Adapters) -> None:
    s = gsvc.register(draft(autonomy_level="l5_self_directed", money_movement=True), "owner.lan")
    sid = s["system_id"]
    eff = gsvc.effective_risk_level(sid)
    assert (eff.level, eff.source) == ("prohibited", "classifier")  # even before a class
    c = _c(gadapters)
    c.draft(sid, "owner.lan")
    c.apply(sid, person("rev.an", "admin"))
    after = gsvc.get(sid)
    assert after["risk_level"] == "prohibited" and after["risk_level_source"] == "classifier"
    assert after["decision33_class"] == "high_risk"
    # a level below l5 does not
    t = gsvc.register(draft(name="T", autonomy_level="l4_autonomous_bounded"), "owner.lan")
    assert gsvc.effective_risk_level(t["system_id"]).level == "unspecified"

"""WP-G2 review fixes: stale draft, decision33_class gate, no lowering by apply, the explicit
downgrade, masked pre-fill, pending ids in check, archived systems."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from supervisor.adapters.factory import Adapters, build_adapters
from supervisor.adapters.llm.mock import MockChat
from supervisor.adapters.masking.vn_regex import VnRegexMasker
from supervisor.config import load_settings
from supervisor.governance import rules as rules_cli
from supervisor.governance.classification import ClassificationService
from supervisor.governance.model import SegregationOfDuties, SystemsError
from supervisor.governance.rules_service import (
    RulesService,
    agents_assigned_control,
    assigned_refs,
)
from supervisor.governance.systems import SystemService
from supervisor.jobs import bootstrap_schema

from .conftest import ListSink, add_agent, draft, person


def _c(a: Adapters, **kw: Any) -> ClassificationService:
    return ClassificationService.from_adapters(a, **kw)


# ---- H2: a stale draft cannot be applied ------------------------------------------------------


def test_stale_draft_is_refused_and_a_fresh_one_applies(
    gsvc: SystemService, gadapters: Adapters
) -> None:
    s = gsvc.register(draft(human_control="pre_approval"), "owner.lan")
    sid = s["system_id"]
    c = _c(gadapters)
    c.draft(sid, "owner.lan")
    c.edit(sid, "owner.lan", {"Q-OTHER": {"answer": "no", "justification": "Checked."}})
    gsvc.update_fields(sid, {"money_movement": True, "human_control": "post_review"}, "owner.lan")
    with pytest.raises(SystemsError, match="changed since the draft; remake it"):
        c.apply(sid, person("rev.an", "admin"))
    assert gsvc.get(sid)["decision33_class"] == "unclassified"
    out = c.draft(sid, "owner.lan")
    assert out["outcome"] == "high_risk"
    c.apply(sid, person("rev.an", "admin"))
    assert gsvc.get(sid)["decision33_class"] == "high_risk"


def test_draft_is_refused_when_the_flow_file_changed(
    gsvc: SystemService, gadapters: Adapters
) -> None:
    s = gsvc.register(draft(money_movement=True), "owner.lan")
    c = _c(gadapters)
    c.draft(s["system_id"], "owner.lan")
    row = gadapters.state.query("classification")[0]
    gadapters.state.update(
        "classification",
        {"classification_id": row["classification_id"]},
        {"flow_sha256": "0" * 64},
        row["row_version"],
    )
    with pytest.raises(SystemsError, match="remake it"):
        c.apply(s["system_id"], person("rev.an", "admin"))


# ---- M1: decision33_class is set only by a classification -------------------------------------


def test_decision33_class_is_not_patchable_with_governance_on(
    gsvc: SystemService, svc: SystemService
) -> None:
    s = gsvc.register(draft(), "owner.lan")
    with pytest.raises(SystemsError, match="set by a classification"):
        gsvc.update_fields(s["system_id"], {"decision33_class": "not_high_risk"}, "owner.lan")
    with pytest.raises(SystemsError, match="unclassified"):
        gsvc.register(draft(name="Other", decision33_class="high_risk"), "owner.lan")
    assert gsvc.register(draft(name="Fine"), "owner.lan")["decision33_class"] == "unclassified"
    # the off path is unchanged
    t = svc.register(draft(), "owner.lan")
    assert (
        svc.update_fields(t["system_id"], {"decision33_class": "high_risk"}, "owner.lan")[
            "decision33_class"
        ]
        == "high_risk"
    )


# ---- M2 / M3: apply never lowers; the downgrade is explicit -----------------------------------


def test_apply_never_lowers_and_prohibited_clears_only_through_the_downgrade_call(
    gsvc: SystemService, gadapters: Adapters, sink: ListSink
) -> None:
    s = gsvc.register(draft(autonomy_level="l5_self_directed", money_movement=True), "owner.lan")
    sid = s["system_id"]
    c = _c(gadapters)
    c.draft(sid, "owner.lan")
    c.apply(sid, person("rev.an", "admin"))
    assert gsvc.get(sid)["risk_level"] == "prohibited"
    gsvc.update_fields(sid, {"autonomy_level": "l3_tool_using_supervised"}, "owner.lan")
    c.draft(sid, "owner.lan")
    c.apply(sid, person("rev.an", "admin"))
    assert gsvc.get(sid)["risk_level"] == "prohibited"  # stuck: apply never lowers
    with pytest.raises(SystemsError, match="downgrade needs a reason"):
        gsvc.update_fields(sid, {"risk_level": "high"}, "owner.lan")
    # the explicit call: reason, not the owner, not below the remaining floor
    with pytest.raises(SystemsError, match="reason is required"):
        gsvc.lower_risk_level(sid, "high", "short", "rev.an")
    with pytest.raises(SegregationOfDuties, match="^segregation of duties:"):
        gsvc.lower_risk_level(sid, "high", "The agent was cut to level three.", "owner.lan")
    with pytest.raises(SystemsError, match="floor of high"):
        gsvc.lower_risk_level(sid, "medium", "The agent was cut to level three.", "rev.an")
    with pytest.raises(SystemsError, match="only lowers"):
        gsvc.lower_risk_level(sid, "prohibited", "The agent was cut to level three.", "rev.an")
    out = gsvc.lower_risk_level(sid, "high", "The agent was cut to level three.", "rev.an")
    assert out["risk_level"] == "high" and out["risk_level_source"] == "manual"
    rec = [p for p in sink.of("system_change") if p["action"] == "risk_lower"][0]
    assert rec["from_level"] == "prohibited" and rec["to_level"] == "high"
    assert len(rec["reason_hash"]) == 64
    assert "cut to level three" not in json.dumps(rec) and "rev.an" not in json.dumps(rec)


def test_lower_route(on: Any) -> None:
    sid = on.ctx.systems.register(
        draft(owner_user="reviewer.an", risk_level="high"), "reviewer.an"
    )["system_id"]
    url = f"/v1/systems/{sid}/risk-level/lower"
    body = {"level": "low", "reason": "Reviewed and agreed by the second line."}
    r = on.client.post(url, json=body, headers={"X-Dev-User": "reviewer.an"})
    assert r.status_code == 400 and r.json()["error"].startswith("segregation of duties:")
    r = on.client.post(url, json=body, headers={"X-Dev-User": "admin.chi"})
    assert r.status_code == 200 and r.json()["risk_level"] == "low"


# ---- M4: masked pre-fill ----------------------------------------------------------------------


def test_prefill_sends_no_cccd_phone_or_name(tmp_path: Path) -> None:
    settings = load_settings(
        sql_backend="sqlite",
        data_dir=tmp_path / "m",
        llm_base_url="",
        governance_enabled=True,
        classifier_ai_prefill=True,
    )
    a = build_adapters(settings)
    bootstrap_schema.run(a.settings, a)
    seen: list[Any] = []

    class Spy(MockChat):
        def complete_json(self, messages: Any, json_schema: Any, timeout_s: Any = None) -> Any:
            seen.append(json.dumps(list(messages), ensure_ascii=False))
            return {"answers": []}

    try:
        purpose = "Hỗ trợ khách Nguyễn Văn An, CCCD 001201012345, số điện thoại 0912345678."
        s = SystemService.from_adapters(a).register(
            draft(name="Secret Name System", purpose=purpose), "owner.lan"
        )
        c = _c(a, chat=Spy(), masker=VnRegexMasker(b"k" * 32, "k"))
        c.draft(s["system_id"], "owner.lan")
        text = seen[0]
        assert "001201012345" not in text and "0912345678" not in text
        assert "Secret Name System" not in text
        # no masker: no purpose at all
        seen.clear()
        _c(a, chat=Spy(), masker=None).draft(s["system_id"], "owner.lan")
        assert "CCCD" not in seen[0] and "Hỗ trợ" not in seen[0]
    finally:
        a.close()


# ---- M5: pending ids --------------------------------------------------------------------------


def test_check_warns_about_ids_that_exist_only_in_pending_folders(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setenv("SQL_BACKEND", "sqlite")
    monkeypatch.setenv("LLM_BASE_URL", "")
    monkeypatch.setenv("DATA_DIR", str(tmp_path / "c"))
    assert rules_cli.main(["check"]) == 0
    out = capsys.readouterr().out
    assert "[WARN] pending: CTL-BANK-PAUSETEST" in out
    assert "[WARN] pending: RSK-SHR-003" in out
    assert "[WARN] pending: CTL-PII-MASK" not in out


# ---- M6: archived systems ---------------------------------------------------------------------


def test_archive_switches_the_assignments_off_and_the_readers_skip_it(
    gsvc: SystemService, gadapters: Adapters
) -> None:
    add_agent(gadapters, "pay-agent")
    s = gsvc.register(draft(user_segment="customer", personal_data="identifiable"), "owner.lan")
    sid = s["system_id"]
    gsvc.link(sid, "agent", "pay-agent", "owner.lan")
    st, se = gadapters.state, gadapters.settings
    assert "CTL-PII-MASK" in assigned_refs(st, se, "pay-agent", "control")
    assert "pay-agent" in agents_assigned_control(st, se, "CTL-PII-MASK")
    gsvc.archive(sid, "owner.lan")
    rows = st.query("assignment", {"system_id": sid})
    assert rows and not any(r["active"] for r in rows)  # switched off, not deleted
    assert assigned_refs(st, se, "pay-agent", "control") == {}
    assert agents_assigned_control(st, se, "CTL-PII-MASK") == frozenset()
    # even with the rows forced on, the readers skip an archived system
    for r in rows:
        st.update(
            "assignment", {"assignment_id": r["assignment_id"]}, {"active": True}, r["row_version"]
        )
    assert agents_assigned_control(st, se, "CTL-PII-MASK") == frozenset()


# ---- lows -------------------------------------------------------------------------------------


def test_rerun_without_change_keeps_last_seen_and_a_failed_apply_keeps_the_draft(
    gsvc: SystemService, gadapters: Adapters
) -> None:
    s = gsvc.register(draft(), "owner.lan")
    sid = s["system_id"]
    rules = RulesService.from_adapters(gadapters)
    before = {r["assignment_id"]: r["last_seen"] for r in gadapters.state.query("assignment")}
    out = rules.run(sid, "owner.lan")
    assert out["added_n"] == out["changed_n"] == out["deactivated_n"] == 0
    after = {r["assignment_id"]: r["last_seen"] for r in gadapters.state.query("assignment")}
    assert before == after
    c = _c(gadapters)
    c.draft(sid, "owner.lan")
    c.edit(sid, "owner.lan", {"Q-OTHER": {"answer": "no", "justification": "Checked."}})
    gsvc.archive(sid, "owner.lan")  # the system can no longer be changed
    with pytest.raises(SystemsError):
        c.apply(sid, person("rev.an", "admin"))
    assert c.get(sid)["draft"] is not None and c.get(sid)["applied"] is None

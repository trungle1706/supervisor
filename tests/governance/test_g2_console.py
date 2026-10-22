"""WP-G2 console: the Rules and Classification tabs of the system page (EN and VI), the forms,
scope and audit."""

from __future__ import annotations

from typing import Any

from supervisor.console import i18n

from .conftest import Console, draft

HX = {"HX-Request": "true"}


def _make(c: Console, user: str = "reviewer.an", **over: Any) -> dict[str, Any]:
    return c.ctx.systems.register(draft(owner_user=user, **over), user)


def _page(c: Console, sid: str, tab: str, lang: str = "en", user: str = "reviewer.an") -> Any:
    return c.get(f"/console/systems/{sid}?tab={tab}&lang={lang}", user=user)


def test_tabs_exist_on_the_system_page(on: Console) -> None:
    sid = _make(on)["system_id"]
    html = _page(on, sid, "overview").text
    assert "tab=rules" in html and "tab=classification" in html
    assert ">Rules<" in html.replace(" ", "").replace("\n", "") or "Rules" in html
    assert _page(on, sid, "zzz").status_code == 400


def test_rules_tab_lists_assignments_with_rule_and_fields(on: Console) -> None:
    sid = _make(on, user_segment="customer", personal_data="identifiable")["system_id"]
    html = _page(on, sid, "rules").text
    assert "CTL-PII-MASK" in html and "AR-PDPL-CUSTOMER" in html
    assert "personal_data, user_segment" in html
    assert "dlp_vn" in html  # the guardian floor
    assert "/console/systems/" + sid + "/rules/run" in html  # the reviewer may run the rules
    vi = _page(on, sid, "rules", "vi").text
    assert "Quy tắc" in vi and "Nghĩa vụ" in vi and "Mức sàn bảo vệ" in vi


def test_rules_tab_shows_switched_off_rows_as_history(on: Console) -> None:
    sid = _make(on, user_segment="customer", personal_data="identifiable")["system_id"]
    on.ctx.systems.update_fields(sid, {"personal_data": "none"}, "reviewer.an")
    html = _page(on, sid, "rules").text
    assert "AR-PDPL-CUSTOMER" in html and ">off<" in html.replace("\n", "").replace("  ", "")


def test_run_rules_from_the_console_is_audited(on: Console) -> None:
    sid = _make(on)["system_id"]
    before = len(on.ctx.tables.query("console_action"))
    r = on.post(f"/console/systems/{sid}/rules/run", {})
    assert r.status_code == 200 and r.headers["HX-Redirect"].endswith("?tab=rules")
    new = on.ctx.tables.query("console_action", order_by=("ts",))[before:]
    assert [x["outcome"] for x in new] == ["attempted", "ok"]
    assert {x["permission"] for x in new} == {"systems.edit"} and {x["target_id"] for x in new} == {
        sid
    }
    assert on.ctx.state.query("assignment", {"system_id": sid})


def test_classification_tab_flow_draft_save_apply(on: Console) -> None:
    sid = _make(on, money_movement=True)["system_id"]
    html = _page(on, sid, "classification").text
    assert "Not applied yet." in html and "There is no draft." in html
    base = f"/console/systems/{sid}/classification"
    r = on.post(f"{base}/draft", {})
    assert r.status_code == 200 and r.headers["HX-Redirect"].endswith("?tab=classification")
    html = _page(on, sid, "classification").text
    assert "Q-MONEY" in html and "from system fields" in html and "High risk" in html
    assert "Illustrative, not legal advice" in html
    # save: the person answers Q-OTHER; untouched rows keep their source
    form = {
        "a_Q-MONEY": "yes",
        "j_Q-MONEY": "from the system field money_movement",
        "a_Q-OTHER": "no",
        "j_Q-OTHER": "Checked by hand.",
    }
    assert on.post(f"{base}/answers", form).status_code == 200
    got = on.ctx.classification.get(sid)["draft"]
    by = {a["id"]: a for a in got["answers"]}
    assert (
        by["Q-OTHER"]["source"] == "person" and by["Q-OTHER"]["justification"] == "Checked by hand."
    )
    assert by["Q-MONEY"]["source"] == "rules"
    # apply
    assert on.post(f"{base}/apply", {}, user="admin.chi").status_code == 200
    assert on.ctx.systems.get(sid)["decision33_class"] == "high_risk"
    html = _page(on, sid, "classification").text
    assert "Applied classification" in html and "High risk" in html
    vi = _page(on, sid, "classification", "vi").text
    assert "Phân loại" in vi and "Rủi ro cao" in vi and "Chưa có bản nháp" in vi


def test_classification_form_errors_are_400_messages(on: Console) -> None:
    sid = _make(on)["system_id"]
    base = f"/console/systems/{sid}/classification"
    for step, msg in (("answers", "no draft"), ("apply", "no draft"), ("bogus", "unknown")):
        r = on.post(f"{base}/{step}", {})
        assert r.status_code == 400 and msg in r.text, step
    on.post(f"{base}/draft", {})
    r = on.post(f"{base}/apply", {})
    assert r.status_code == 400 and "not complete" in r.text
    r = on.post(f"{base}/answers", {"a_Q-OTHER": "yes", "j_Q-OTHER": "x" * 600})
    assert r.status_code == 400


def test_ai_prefilled_answers_are_labelled_and_need_a_confirmation(on: Console) -> None:
    from supervisor.adapters.llm.mock import MockChat
    from supervisor.governance.classification import ClassificationService

    on.ctx.settings.classifier_ai_prefill = True
    chat = MockChat()
    chat.add_script(
        "pf",
        [{"answers": [{"id": "Q-OTHER", "answer": "no", "justification": "Nothing found."}]}],
    )
    svc = ClassificationService(
        on.ctx.state,
        on.ctx.tables,
        on.ctx.clock,
        on.ctx.settings,
        evidence=on.runtime.chain,
        chat=chat,
    )
    on.ctx._classification = svc
    sid = _make(on, human_control="pre_approval")["system_id"]
    with chat.scenario("pf"):
        out = svc.draft(sid, "reviewer.an")
    assert out["ai_prefill"]["mock"] is True
    html = _page(on, sid, "classification").text
    assert "AI pre-fill" in html and "mock model" in html and "[mock] Nothing found." in html
    assert 'name="confirm_ai_prefill"' in html
    base = f"/console/systems/{sid}/classification"
    r = on.post(f"{base}/apply", {}, user="admin.chi")
    assert r.status_code == 400 and "AI pre-filled" in r.text
    assert (
        on.post(f"{base}/apply", {"confirm_ai_prefill": "1"}, user="admin.chi").status_code == 200
    )
    assert on.ctx.systems.get(sid)["decision33_class"] == "not_high_risk"


def test_scoped_viewer_sees_tabs_read_only_and_cannot_post(on: Console) -> None:
    sid = _make(on)["system_id"]
    on.ctx.systems.add_member(sid, "viewer.hoa", "data_steward", "reviewer.an")
    on.ctx.classification.draft(sid, "reviewer.an")
    for tab in ("rules", "classification"):
        html = _page(on, sid, tab, user="viewer.hoa").text
        assert 'name="a_' not in html and "/rules/run" not in html and "/draft" not in html
    assert "Q-MONEY" in _page(on, sid, "classification", user="viewer.hoa").text
    on.ctx.settings.api_rbac_enabled = True
    try:
        r = on.post(f"/console/systems/{sid}/classification/draft", {}, user="viewer.hoa")
        assert r.status_code == 403
    finally:
        on.ctx.settings.api_rbac_enabled = False
    other = _make(on, name="Hidden", owner_team="risk-team")["system_id"]
    assert _page(on, other, "rules", user="viewer.hoa").status_code == 400


def test_new_strings_exist_in_both_languages() -> None:
    table = i18n.table()
    keys = [
        k
        for k in table
        if k.startswith(("sy_tab_rules", "sy_rule", "sy_cls", "sy_kind", "sy_rules"))
    ]
    assert len(keys) >= 40
    assert all(table[k][0].strip() and table[k][1].strip() for k in keys)

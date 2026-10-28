# ruff: noqa: F811  (pytest fixtures are imported and then named as arguments)
"""WP-P2 (phase 8, CONSOLE_STATE_ACTIONS): separation of duties in two governance actions.

* Decision 33 apply: the system owner cannot apply the class on the own system
  (``owner_cannot_apply``); every answer a person gives needs a justification of 20 characters.
* Guardian switch-off: a reason is required; on a system in production or at high risk a second
  person approves before the binding takes effect (``same_person`` for the requester); the
  mandatory floor is never switchable.

Each rule with the flag on and off. People are the synthetic ones of config/users.yaml."""

from __future__ import annotations

from typing import Any

import pytest

from supervisor.governance.guardians import GuardianNarrower

from .conftest import Console, draft, mounted, on  # noqa: F401  (fixtures)

REVIEWER = "reviewer.an"
SECOND = "reviewer.binh"
VIEWER = "viewer.hoa"
LONG = "The flow was checked against the product description."  # 20 characters or more


@pytest.fixture
def gon(on: Console, monkeypatch: pytest.MonkeyPatch) -> Console:
    for flag in ("guardian_bindings_enabled", "console_catalog_enabled", "detectors_enabled"):
        monkeypatch.setattr(on.ctx.settings, flag, True)
    monkeypatch.setattr(on.ctx.settings, "judge_enabled", True)
    return on


@pytest.fixture
def pon(gon: Console, monkeypatch: pytest.MonkeyPatch) -> Console:
    monkeypatch.setattr(gon.ctx.settings, "console_state_actions", True)
    return gon


def req(c: Console, method: str, url: str, body: Any = None, user: str = REVIEWER) -> Any:
    return c.client.request(method, url, json=body, headers={"X-Dev-User": user})


def create(c: Console, user: str = REVIEWER, **over: Any) -> str:
    r = req(
        c,
        "POST",
        "/v1/systems",
        draft(**{"owner_user": user, "personal_data": "none", **over}),
        user,
    )
    assert r.status_code == 201, r.text
    return str(r.json()["system_id"])


def production(c: Console, sid: str) -> None:
    row = c.ctx.state.get("ai_system", {"system_id": sid})
    c.ctx.state.update(
        "ai_system", {"system_id": sid}, {"lifecycle_stage": "operation"}, row["row_version"]
    )


def put_off(
    c: Console, sid: str, slug: str = "injection_regex", reason: Any = LONG, user: str = REVIEWER
) -> Any:
    body: dict[str, Any] = {"state": "off"}
    if reason is not None:
        body["reason"] = reason
    return req(c, "PUT", f"/v1/systems/{sid}/guardians/{slug}", body, user)


def binding(c: Console, sid: str, slug: str = "injection_regex") -> dict[str, Any] | None:
    row = c.ctx.state.get("guardian_binding", {"system_id": sid, "feature_slug": slug})
    return dict(row) if row else None


# ============================================================ Decision 33: owner cannot apply


def _drafted(c: Console, owner: str = REVIEWER) -> str:
    sid = create(c, owner, money_movement=True)
    r = req(c, "POST", f"/v1/systems/{sid}/classification", None, owner)
    assert r.status_code in (200, 201), r.text
    return sid


def test_flag_default_off(gon: Console) -> None:
    assert gon.ctx.settings.console_state_actions is False


def test_off_the_owner_can_still_apply_and_short_justifications_pass(gon: Console) -> None:
    sid = _drafted(gon)
    r = req(
        gon,
        "PATCH",
        f"/v1/systems/{sid}/classification",
        {"answers": {"Q-OTHER": {"answer": "no", "justification": "ok"}}},
    )
    assert r.status_code == 200, r.text
    r = req(gon, "POST", f"/v1/systems/{sid}/classification/apply", {})
    assert r.status_code == 200, r.text  # the owner applied the class on the own system
    assert r.json()["applied"]["outcome"] == "high_risk"


def test_on_the_owner_cannot_apply_another_person_can(pon: Console) -> None:
    sid = _drafted(pon)
    r = req(pon, "POST", f"/v1/systems/{sid}/classification/apply", {})
    assert r.status_code == 400 and "owner_cannot_apply" in r.json()["error"]
    assert pon.ctx.systems.get(sid)["decision33_class"] == "unclassified"
    r = req(pon, "POST", f"/v1/systems/{sid}/classification/apply", {}, SECOND)
    assert r.status_code == 200, r.text
    assert pon.ctx.systems.get(sid)["decision33_class"] == "high_risk"


def test_on_a_team_system_owner_cannot_apply_either(pon: Console) -> None:
    sid = _drafted(pon, owner=SECOND)
    pon.ctx.systems.add_member(sid, REVIEWER, "system_owner", SECOND)
    r = req(pon, "POST", f"/v1/systems/{sid}/classification/apply", {}, REVIEWER)
    assert r.status_code == 400 and "owner_cannot_apply" in r.json()["error"]
    r = req(pon, "POST", f"/v1/systems/{sid}/classification/apply", {}, SECOND)
    assert r.status_code == 400 and "owner_cannot_apply" in r.json()["error"]


def test_on_every_person_answer_needs_twenty_characters(pon: Console) -> None:
    sid = _drafted(pon)
    url = f"/v1/systems/{sid}/classification"
    for why in (None, "", "ok", "x" * 19):
        body = {"Q-OTHER": {"answer": "no"}}
        if why is not None:
            body["Q-OTHER"]["justification"] = why
        r = req(pon, "PATCH", url, {"answers": body})
        assert r.status_code == 400 and "justification_too_short" in r.json()["error"], why
    r = req(
        pon, "PATCH", url, {"answers": {"Q-OTHER": {"answer": "no", "justification": "x" * 20}}}
    )
    assert r.status_code == 200, r.text
    # clearing an answer needs no justification
    r = req(pon, "PATCH", url, {"answers": {"Q-OTHER": {"answer": None}}})
    assert r.status_code == 200, r.text


def test_on_apply_refuses_a_short_justification_saved_before_the_flag(
    gon: Console, monkeypatch: pytest.MonkeyPatch
) -> None:
    sid = _drafted(gon)
    req(
        gon,
        "PATCH",
        f"/v1/systems/{sid}/classification",
        {"answers": {"Q-OTHER": {"answer": "no", "justification": "ok"}}},
    )
    monkeypatch.setattr(gon.ctx.settings, "console_state_actions", True)
    r = req(gon, "POST", f"/v1/systems/{sid}/classification/apply", {}, SECOND)
    assert r.status_code == 400 and "justification_too_short" in r.json()["error"]
    assert "Q-OTHER" in r.json()["error"]


def test_console_form_and_hint(pon: Console) -> None:
    sid = _drafted(pon)
    page = pon.get(f"/console/systems/{sid}?tab=classification&lang=en").text
    assert 'data-min-why="20"' in page and "at least 20 characters" in page
    base = f"/console/systems/{sid}/classification"
    r = pon.post(f"{base}/answers", {"a_Q-OTHER": "no", "j_Q-OTHER": "short"})
    assert r.status_code == 400 and "justification_too_short" in r.text
    r = pon.post(f"{base}/apply", {})
    assert r.status_code == 400 and "owner_cannot_apply" in r.text
    r = pon.post(f"{base}/apply", {}, user=SECOND)
    assert r.status_code == 200


def test_console_off_has_no_hint(gon: Console) -> None:
    sid = _drafted(gon)
    page = gon.get(f"/console/systems/{sid}?tab=classification&lang=en").text
    assert "data-min-why" not in page


# ============================================================ guardian switch-off


def test_off_path_switch_off_needs_no_reason_and_no_second_person(gon: Console) -> None:
    sid = create(gon)
    production(gon, sid)
    r = put_off(gon, sid, reason=None)
    assert r.status_code == 200 and r.json()["state"] == "off" and "pending_request" not in r.json()
    body = req(gon, "GET", f"/v1/systems/{sid}/guardians").json()
    assert "pending_off" not in body  # the off path adds no key
    assert gon.ctx.state.query("guardian_off_request") == []


def test_on_the_reason_is_required(pon: Console) -> None:
    sid = create(pon)
    for reason in (None, "", "   "):
        r = put_off(pon, sid, reason=reason)
        assert r.status_code == 400 and "reason_required" in r.json()["error"]
    assert binding(pon, sid) is None
    # switching on again needs no reason
    assert put_off(pon, sid).status_code == 200
    r = req(pon, "PUT", f"/v1/systems/{sid}/guardians/injection_regex", {"state": "on"})
    assert r.status_code == 200 and r.json()["state"] == "on"


def test_on_a_plain_system_switches_off_at_once(pon: Console) -> None:
    sid = create(pon)
    r = put_off(pon, sid)
    assert r.status_code == 200 and r.json()["state"] == "off" and r.json()["effective"] is False
    assert "pending_request" not in r.json()
    assert pon.ctx.state.query("guardian_off_request") == []


@pytest.mark.parametrize("how", ["production", "high_risk"])
def test_on_production_or_high_risk_waits_for_a_second_person(pon: Console, how: str) -> None:
    sid = create(pon)
    if how == "production":
        production(pon, sid)
    else:
        pon.ctx.systems.update_fields(sid, {"risk_level": "high"}, REVIEWER)
    r = put_off(pon, sid)
    assert r.status_code == 200, r.text
    out = r.json()
    assert out["state"] == "on" and out["effective"] is True  # nothing took effect yet
    assert out["pending_request"]["status"] == "pending"
    assert out["pending_request"]["requested_by"] == REVIEWER
    assert binding(pon, sid) is None
    rid = out["pending_request"]["request_id"]
    # the list on GET
    got = req(pon, "GET", f"/v1/systems/{sid}/guardians").json()["pending_off"]
    assert [p["request_id"] for p in got] == [rid]
    # a second request for the same feature is refused
    r = put_off(pon, sid, user=SECOND)
    assert r.status_code == 400 and "request_pending" in r.json()["error"]
    # the requester cannot approve
    url = f"/v1/systems/{sid}/guardian-off-requests/{rid}/decide"
    r = req(pon, "POST", url, {"decision": "approve"}, REVIEWER)
    assert r.status_code == 400 and "same_person" in r.json()["error"]
    assert binding(pon, sid) is None
    # a viewer may not decide at all
    assert req(pon, "POST", url, {"decision": "approve"}, VIEWER).status_code == 403
    # a second person approves: the binding takes effect, set_by is the requester
    r = req(pon, "POST", url, {"decision": "approve"}, SECOND)
    assert r.status_code == 200, r.text
    assert r.json()["state"] == "off" and r.json()["request_status"] == "approved"
    row = binding(pon, sid)
    assert row is not None and row["state"] == "off" and row["set_by"] == REVIEWER
    assert row["reason"] == LONG
    req_row = pon.ctx.state.get("guardian_off_request", {"request_id": rid})
    assert req_row["status"] == "approved" and req_row["decided_by"] == SECOND
    # answered once
    r = req(pon, "POST", url, {"decision": "approve"}, SECOND)
    assert r.status_code == 400 and "already answered" in r.json()["error"]
    # the engines see it
    narrow = GuardianNarrower(pon.ctx.state, pon.ctx.settings, ttl_s=0)
    pon.ctx.systems.link(sid, "agent", "payments", REVIEWER)
    assert "injection_regex" in narrow.off("payments")


def test_on_a_rejected_request_changes_nothing(pon: Console) -> None:
    sid = create(pon)
    production(pon, sid)
    rid = put_off(pon, sid).json()["pending_request"]["request_id"]
    url = f"/v1/systems/{sid}/guardian-off-requests/{rid}/decide"
    r = req(pon, "POST", url, {"decision": "reject"}, SECOND)
    assert r.status_code == 200 and r.json()["request_status"] == "rejected"
    assert binding(pon, sid) is None and r.json()["state"] == "on"
    assert req(pon, "POST", url, {"decision": "maybe"}, SECOND).status_code == 400
    # a new request is possible after the answer
    assert put_off(pon, sid).json()["pending_request"]["request_id"] != rid


def test_on_the_floor_is_never_switchable_even_on_production(pon: Console) -> None:
    sid = create(pon, user_segment="customer", personal_data="identifiable")
    production(pon, sid)
    r = put_off(pon, sid, slug="dlp_vn")
    assert r.status_code == 400 and "guardian floor" in r.json()["error"]
    assert pon.ctx.state.query("guardian_off_request") == []
    assert binding(pon, sid, "dlp_vn") is None


def test_on_a_floor_added_after_the_request_blocks_the_approval(pon: Console) -> None:
    sid = create(pon)
    production(pon, sid)
    rid = put_off(pon, sid, slug="dlp_vn").json()["pending_request"]["request_id"]
    pon.ctx.systems.update_fields(
        sid, {"user_segment": "customer", "personal_data": "identifiable"}, REVIEWER
    )
    url = f"/v1/systems/{sid}/guardian-off-requests/{rid}/decide"
    r = req(pon, "POST", url, {"decision": "approve"}, SECOND)
    assert r.status_code == 400 and "guardian floor" in r.json()["error"]
    assert binding(pon, sid, "dlp_vn") is None
    assert pon.ctx.state.get("guardian_off_request", {"request_id": rid})["status"] == "pending"


def test_off_the_decide_route_answers_400_with_the_flag_name(gon: Console) -> None:
    sid = create(gon)
    r = req(
        gon,
        "POST",
        f"/v1/systems/{sid}/guardian-off-requests/gof_x/decide",
        {"decision": "approve"},
        SECOND,
    )
    assert r.status_code == 400 and "CONSOLE_STATE_ACTIONS=1" in r.json()["error"]


def test_on_two_audit_rows_and_chain_records(pon: Console) -> None:
    sid = create(pon)
    production(pon, sid)
    before = len(pon.ctx.tables.query("console_action"))
    rid = put_off(pon, sid).json()["pending_request"]["request_id"]
    rows = pon.ctx.tables.query("console_action", order_by=("ts",))[before:]
    assert [r["outcome"] for r in rows] == ["attempted", "ok"]
    assert rows[1]["detail"] == "guardian injection_regex off requested"
    req(
        pon,
        "POST",
        f"/v1/systems/{sid}/guardian-off-requests/{rid}/decide",
        {"decision": "approve"},
        SECOND,
    )
    rows = pon.ctx.tables.query("console_action", order_by=("ts",))[before + 2 :]
    assert [r["permission"] for r in rows] == ["systems.approve"] * 2
    assert [r["outcome"] for r in rows] == ["attempted", "ok"]


# --------------------------------------------------------------------------- Catalog page


def test_catalog_off_has_no_reason_field_and_no_pending_list(gon: Console) -> None:
    sid = create(gon)
    html = gon.get(f"/console/catalog?system={sid}&lang=en").text
    assert "/guardians/injection_regex" in html
    assert 'name="reason"' not in html and "data-gb-second" not in html


def test_catalog_on_reason_field_pending_list_and_approve_buttons(pon: Console) -> None:
    sid = create(pon)
    production(pon, sid)
    html = pon.get(f"/console/catalog?system={sid}&lang=en").text
    assert 'name="reason"' in html and "data-gb-second" in html
    # switch off through the console form: a request, not a binding
    r = pon.post(
        f"/console/systems/{sid}/guardians/injection_regex",
        {"state": "off", "reason": LONG},
    )
    assert r.status_code == 200 and r.headers["HX-Redirect"].startswith("/console/catalog")
    assert binding(pon, sid) is None
    rid = pon.ctx.guardians.pending_off(sid)[0]["request_id"]
    mine = pon.get(f"/console/catalog?system={sid}&lang=en").text
    assert 'data-section="gb-pending"' in mine and rid in mine
    assert "guardian-requests" not in mine and "You asked for this" in mine
    other = pon.get(f"/console/catalog?system={sid}&lang=en", user=SECOND).text
    assert (
        f"/guardian-requests/{rid}/approve" in other and f"/guardian-requests/{rid}/reject" in other
    )
    # the requester is refused, a second person approves
    url = f"/console/systems/{sid}/guardian-requests/{rid}/approve"
    r = pon.post(url, {})
    assert r.status_code == 400 and "same_person" in r.text
    r = pon.post(url, {}, user=SECOND)
    assert r.status_code == 200 and r.headers["HX-Redirect"].startswith("/console/catalog")
    row = binding(pon, sid)
    assert row is not None and row["state"] == "off"
    done = pon.get(f"/console/catalog?system={sid}&lang=en").text
    assert 'data-section="gb-pending"' not in done
    # no reason through the console form: 400
    r = pon.post(f"/console/systems/{sid}/guardians/monitor_drift", {"state": "off"})
    assert r.status_code == 400 and "reason_required" in r.text

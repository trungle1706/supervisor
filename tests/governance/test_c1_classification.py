# ruff: noqa: F811  (pytest fixtures are imported and then named as arguments)
"""WP-C1 (phase 12, CLASSIFICATION_V2): the classification tree service, API and console.

Each rule with the flag on and off: level mapping and floor, the second person who approves,
the Decision 33 sub-flow, 400 codes, the HTMX fragments, the chain record and the audit rows.
People are the synthetic ones of config/users.yaml."""

from __future__ import annotations

import datetime as dt
from typing import Any

import pytest

from supervisor.governance import classification_v2 as c2

from .conftest import Console, draft, mounted, on  # noqa: F401  (fixtures)
from .test_n3_register import S1, S2, new, step

DECIDER = "reviewer.an"
APPROVER = "reviewer.binh"
VIEWER = "viewer.hoa"
OWNER_APPROVER = "admin.chi"
HX = {"HX-Request": "true"}
SHORT = "Checked against the product description."


def req(c: Console, method: str, url: str, body: Any = None, user: str = DECIDER) -> Any:
    return c.client.request(method, url, json=body, headers={"X-Dev-User": user})


@pytest.fixture
def v2(on: Console, monkeypatch: pytest.MonkeyPatch) -> Console:
    monkeypatch.setattr(on.ctx.settings, "classification_v2", True)
    return on


_N = [0]


def create(c: Console, **over: Any) -> str:
    _N[0] += 1
    r = req(c, "POST", "/v1/systems", draft(**{"name": f"Classified system {_N[0]}", **over}))
    assert r.status_code == 201, r.text
    return str(r.json()["system_id"])


def system(c: Console, sid: str) -> dict[str, Any]:
    return dict(c.ctx.state.get("ai_system", {"system_id": sid}))


def url(sid: str, tail: str = "") -> str:
    return f"/v1/systems/{sid}/classification-v2{tail}"


NOT_LISTED = {"Q-OTHER": {"answer": "no", "justification": SHORT}}


def medium_body() -> dict[str, Any]:
    return {
        "answers": {
            "N-SYSTEM": {"answer": "yes", "evidence": "table:system_component/1"},
            "N-PROHIBITED": {"answer": "no", "note": "No forbidden purpose."},
            "N-CONFUSE": {"answer": "yes", "evidence": "doc:chat-screen-3"},
        },
        "decision33": NOT_LISTED,
    }


def high_body(cert: str = "no", threshold: str = "yes") -> dict[str, Any]:
    return {
        "answers": {
            "N-SYSTEM": {"answer": "yes"},
            "N-PROHIBITED": {"answer": "no"},
            "N-THRESHOLD": {"answer": threshold, "evidence": "doc:limits-v2"},
            "N-CERT": {"answer": cert},
            "N-CONFUSE": {"answer": "no"},
        },
        "decision33": NOT_LISTED,
    }


def decide(c: Console, sid: str, body: dict[str, Any], user: str = DECIDER) -> Any:
    return req(c, "POST", url(sid), body, user)


def approve(c: Console, sid: str, user: str = APPROVER) -> Any:
    return req(c, "POST", url(sid, "/approve"), {}, user)


# ============================================================ off path


def test_flag_default_off(on: Console) -> None:
    assert on.ctx.settings.classification_v2 is False
    assert on.ctx.settings.classification_config.name == "classification.yaml"


def test_off_every_route_answers_400_with_the_code(on: Console) -> None:
    sid = create(on)
    for method, path in (
        ("GET", url(sid)),
        ("POST", url(sid)),
        ("POST", url(sid, "/approve")),
        ("GET", "/v1/classification/summary"),
        ("GET", f"/console/systems/{sid}/classify"),
        ("POST", f"/console/systems/{sid}/classify"),
        ("POST", f"/console/systems/{sid}/classify/approve"),
    ):
        r = on.client.request(
            method,
            path,
            json={} if path.startswith("/v1") else None,
            headers={"X-Dev-User": DECIDER, "HX-Request": "true"},
        )
        assert r.status_code == 400, (method, path, r.status_code)
        assert "classification_v2_off" in r.text, (method, path)
    assert on.ctx.state.query("classification_v2", {}) == []


def test_off_the_decision33_flow_is_unchanged(on: Console) -> None:
    sid = create(on, money_movement=True)
    r = req(on, "POST", f"/v1/systems/{sid}/classification")
    assert r.status_code == 201 and r.json()["outcome"] == "high_risk"  # Decision 33 draft
    got = req(on, "GET", f"/v1/systems/{sid}/classification").json()
    assert got["draft"]["outcome"] == "high_risk" and got["applied"] is None
    assert "/classify" not in on.get(f"/console/systems/{sid}?tab=classification").text


# ============================================================ decide and approve


def test_medium_path_decide_then_a_second_person_approves(v2: Console) -> None:
    sid = create(v2, user_segment="customer")
    r = decide(v2, sid, medium_body())
    assert r.status_code == 201, r.text
    rec = r.json()
    assert rec["outcome"] == "medium" and rec["status"] == "pending_approval"
    assert rec["level"] == "medium" and rec["decided_by"] == DECIDER and rec["approved_by"] is None
    assert [s["node"] for s in rec["path"]] == [
        "N-SYSTEM",
        "N-PROHIBITED",
        "N-PM-LIST",
        "N-CONFUSE",
    ]
    assert rec["path"][2]["source"] == "decision33" and rec["path"][2]["answer"] == "not_high_risk"
    assert rec["path"][0]["evidence"] == "table:system_component/1"
    assert system(v2, sid)["risk_level"] == "unspecified"  # nothing changes before approval
    r = approve(v2, sid)
    assert r.status_code == 200, r.text
    out = r.json()
    assert out["status"] == "approved" and out["approved_by"] == APPROVER
    s = system(v2, sid)
    assert s["risk_level"] == "medium" and s["risk_level_source"] == "classifier"
    assert s["decision33_class"] == "not_high_risk"  # the existing apply ran for the sub-flow
    got = req(v2, "GET", url(sid)).json()
    assert got["current"]["outcome"] == "medium" and got["pending"] is None
    assert got["records_n"] == 1 and got["thresholds_vnd"]["credit_vnd"] == 50_000_000
    assert [t["id"] for t in got["not_triggers"]] == ["NT-ROUTINE"]


def test_high_paths_set_high_and_call_decision33_apply(v2: Console) -> None:
    for cert, outcome in (("yes", "high_certify"), ("no", "high_self")):
        sid = create(v2, money_movement=True)
        body = high_body(cert)
        r = decide(v2, sid, body)
        assert r.status_code == 201, r.text
        assert r.json()["outcome"] == outcome and r.json()["level"] == "high"
        assert r.json()["path"][2]["d33"]["outcome"] == "high_risk"
        assert approve(v2, sid).status_code == 200
        s = system(v2, sid)
        assert s["risk_level"] == "high" and s["decision33_class"] == "high_risk"


def test_threshold_not_met_overrules_the_list_and_skips_decision33_apply(v2: Console) -> None:
    sid = create(v2, money_movement=True)
    r = decide(v2, sid, high_body(threshold="no"))
    assert r.status_code == 201 and r.json()["outcome"] == "low"
    assert approve(v2, sid).status_code == 200
    s = system(v2, sid)
    assert s["risk_level"] == "low"
    assert s["decision33_class"] == "unclassified"  # the list said high; the tree did not apply it


def test_prohibited_raises_the_level_to_prohibited(v2: Console) -> None:
    sid = create(v2)
    body = {"answers": {"N-SYSTEM": {"answer": "yes"}, "N-PROHIBITED": {"answer": "yes"}}}
    assert decide(v2, sid, body).json()["outcome"] == "prohibited"
    assert approve(v2, sid).status_code == 200
    assert system(v2, sid)["risk_level"] == "prohibited"


def test_not_a_system_changes_nothing(v2: Console) -> None:
    sid = create(v2)
    assert (
        decide(v2, sid, {"answers": {"N-SYSTEM": {"answer": "no"}}}).json()["outcome"]
        == "not_system"
    )
    before = system(v2, sid)
    assert approve(v2, sid).status_code == 200
    after = system(v2, sid)
    assert after["risk_level"] == before["risk_level"] == "unspecified"
    assert after["decision33_class"] == before["decision33_class"]


def test_the_floor_never_lowers_the_level(v2: Console) -> None:
    sid = create(v2, user_segment="customer")
    row = v2.ctx.state.get("ai_system", {"system_id": sid})
    v2.ctx.state.update("ai_system", {"system_id": sid}, {"risk_level": "high"}, row["row_version"])
    body = {
        "answers": {
            "N-SYSTEM": {"answer": "yes"},
            "N-PROHIBITED": {"answer": "no"},
            "N-CONFUSE": {"answer": "no"},
        },
        "decision33": NOT_LISTED,
    }
    assert decide(v2, sid, body).json()["outcome"] == "low"
    assert approve(v2, sid).status_code == 200
    assert system(v2, sid)["risk_level"] == "high"  # low never lowers high


def test_prefill_rules_answer_and_the_page_says_so(v2: Console) -> None:
    sid = create(v2, user_segment="customer", system_type="assistant")
    body = {"answers": {"N-PROHIBITED": {"answer": "no"}}, "decision33": NOT_LISTED}
    r = req(v2, "POST", url(sid) + "?preview=1", body)
    assert r.status_code == 200, r.text
    nodes = {n["id"]: n for n in r.json()["nodes"]}
    assert nodes["N-SYSTEM"]["state"] == "open"  # no agent linked: the rule stays quiet
    assert r.json()["pending"] == "N-SYSTEM" and not r.json()["complete"]
    body["answers"]["N-SYSTEM"] = {"answer": "yes"}
    r = req(v2, "POST", url(sid) + "?preview=1", body)
    nodes = {n["id"]: n for n in r.json()["nodes"]}
    assert nodes["N-CONFUSE"]["step"]["source"] == "rules"  # customer-facing assistant
    assert nodes["N-SYSTEM"]["step"]["source"] == "person" and r.json()["outcome"] == "medium"
    assert (
        v2.ctx.state.query("classification_v2", {"system_id": sid}) == []
    )  # preview stores nothing


def test_inherited_from_provider_and_valid_until(v2: Console) -> None:
    sid = create(v2)
    body = {**medium_body(), "inherited_from_provider": True}
    rec = decide(v2, sid, body).json()
    assert rec["inherited_from_provider"] is True and rec["review_due"] is False
    assert rec["valid_until"] > rec["created_at"]
    year = dt.datetime.fromisoformat(rec["valid_until"].replace("Z", "+00:00"))
    start = dt.datetime.fromisoformat(rec["created_at"].replace("Z", "+00:00"))
    assert (year - start).days == c2.VALID_DAYS  # reviewed every year (Circular 53 Art. 4(5))


# ============================================================ separation of duties


def test_the_decider_cannot_approve_the_own_record(v2: Console) -> None:
    sid = create(v2)
    decide(v2, sid, medium_body(), APPROVER)  # reviewer.binh decides
    r = approve(v2, sid, APPROVER)
    assert r.status_code == 400 and "same_person" in r.json()["error"]
    assert system(v2, sid)["risk_level"] == "unspecified"
    assert approve(v2, sid, DECIDER).status_code == 200  # another person may


def test_the_system_owner_cannot_approve(v2: Console) -> None:
    sid = create(v2, owner_user=DECIDER)
    decide(v2, sid, medium_body(), APPROVER)
    r = approve(v2, sid, DECIDER)
    assert r.status_code == 400 and "owner_cannot_approve" in r.json()["error"]
    v2.ctx.systems.add_member(sid, OWNER_APPROVER, "system_owner", APPROVER)
    r = approve(v2, sid, OWNER_APPROVER)
    assert r.status_code == 400 and "owner_cannot_approve" in r.json()["error"]  # a team owner too
    assert system(v2, sid)["risk_level"] == "unspecified"


def test_approve_needs_the_permission_and_a_record(v2: Console) -> None:
    sid = create(v2)
    r = approve(v2, sid)
    assert r.status_code == 400 and "no_record" in r.json()["error"]
    decide(v2, sid, medium_body())
    assert approve(v2, sid, VIEWER).status_code == 403
    assert approve(v2, sid).status_code == 200
    r = approve(v2, sid)
    assert r.status_code == 400 and "already_approved" in r.json()["error"]


def test_a_new_decision_after_approval_waits_for_its_own_approval(v2: Console) -> None:
    sid = create(v2)
    decide(v2, sid, medium_body())
    approve(v2, sid)
    decide(v2, sid, {"answers": {"N-SYSTEM": {"answer": "no"}}})
    got = req(v2, "GET", url(sid)).json()
    assert got["current"]["outcome"] == "medium" and got["pending"]["outcome"] == "not_system"
    assert got["records_n"] == 2


def test_tree_file_change_between_decision_and_approval_is_refused(
    v2: Console, monkeypatch: pytest.MonkeyPatch, tmp_path: Any
) -> None:
    sid = create(v2)
    decide(v2, sid, medium_body())
    other = tmp_path / "classification.yaml"
    other.write_text(
        v2.ctx.settings.classification_config.read_text("utf-8") + "\n# edited\n", encoding="utf-8"
    )
    monkeypatch.setattr(v2.ctx.settings, "classification_config", other)
    r = approve(v2, sid)
    assert r.status_code == 400 and "tree_changed" in r.json()["error"]


def test_decision33_apply_refusal_leaves_the_record_waiting(v2: Console) -> None:
    sid = create(v2, money_movement=True, autonomy_level="unspecified")
    assert decide(v2, sid, high_body()).status_code == 201
    r = approve(v2, sid)
    assert r.status_code == 400 and "autonomy_level" in r.json()["error"]  # the apply rule holds
    rows = v2.ctx.state.query("classification_v2", {"system_id": sid})
    assert rows[0]["approved_by"] is None and rows[0]["approved_at"] is None  # put back
    assert system(v2, sid)["risk_level"] == "unspecified"
    row = v2.ctx.state.get("ai_system", {"system_id": sid})
    v2.ctx.state.update(
        "ai_system", {"system_id": sid}, {"autonomy_level": "l1_assistive"}, row["row_version"]
    )
    assert approve(v2, sid).status_code == 200
    assert system(v2, sid)["risk_level"] == "high"


# ============================================================ 400 codes


@pytest.mark.parametrize(
    ("body", "code"),
    [
        ({"answers": {"N-NOPE": {"answer": "yes"}}}, "unknown_node"),
        ({"answers": {"N-SYSTEM": {"answer": "maybe"}}}, "bad_answer"),
        ({"answers": {"N-SYSTEM": {"answer": "excluded"}}}, "bad_answer"),
        ({"answers": {"N-PM-LIST": {"answer": "high_risk"}}}, "bad_answer"),
        ({"answers": {"N-SYSTEM": {"answer": "yes", "color": "x"}}}, "bad_answer"),
        ({"answers": {"N-SYSTEM": {"answer": "no", "evidence": "x" * 201}}}, "bad_answer"),
        ({"answers": {"N-SYSTEM": {"answer": "no", "note": "x" * 301}}}, "bad_answer"),
        ({"answers": {"N-SYSTEM": {"answer": "no", "note": "a\x01b"}}}, "bad_answer"),
        ({"answers": ["x"]}, "bad_input"),
        ({"extra": 1}, "bad_input"),
        ({"inherited_from_provider": "yes"}, "bad_input"),
        ({"decision33": {"Q-NOPE": {"answer": "yes"}}}, "unknown_node"),
        ({"decision33": {"Q-OTHER": {"answer": "perhaps"}}}, "bad_answer"),
        ({"decision33": "x"}, "bad_answer"),
        ({"answers": {"N-SYSTEM": {"answer": "yes"}}}, "incomplete_path"),
        ({}, "incomplete_path"),
    ],
)
def test_bad_input_is_400_with_a_code_never_500(
    v2: Console, body: dict[str, Any], code: str
) -> None:
    sid = create(v2)
    r = decide(v2, sid, body)
    assert r.status_code == 400, r.text
    assert code in r.json()["error"]
    assert v2.ctx.state.query("classification_v2", {"system_id": sid}) == []


def test_not_json_and_unknown_system(v2: Console) -> None:
    sid = create(v2)
    r = v2.client.post(url(sid), content=b"[1,2]", headers={"X-Dev-User": DECIDER})
    assert r.status_code == 400
    r = v2.client.post(url(sid), content=b"{oops", headers={"X-Dev-User": DECIDER})
    assert r.status_code == 400
    assert req(v2, "GET", url("sys-nope")).status_code == 404
    assert decide(v2, "sys-nope", medium_body()).status_code == 404
    assert approve(v2, "sys-nope").status_code == 404
    assert req(v2, "GET", url("bad id!")).status_code == 400


def test_viewer_reads_but_cannot_decide(v2: Console) -> None:
    sid = create(v2)
    assert req(v2, "GET", url(sid), user="auditor.dung").status_code == 200
    assert decide(v2, sid, medium_body(), VIEWER).status_code == 403


def test_archived_system_is_refused(v2: Console) -> None:
    sid = create(v2)
    assert req(v2, "POST", f"/v1/systems/{sid}/archive", {}).status_code == 200
    r = decide(v2, sid, medium_body())
    assert r.status_code == 400 and "archived" in r.json()["error"]


# ============================================================ summary, chain, audit


def test_summary_counts_per_outcome(v2: Console) -> None:
    a, b, c = create(v2, name="A"), create(v2, name="B"), create(v2, name="C")
    decide(v2, a, medium_body())
    approve(v2, a)
    decide(v2, b, medium_body())  # waits for approval
    s = req(v2, "GET", "/v1/classification/summary").json()
    assert s["counts"]["medium"] == 1 and s["approved_n"] == 1
    assert s["waiting_for_approval_n"] == 1 and s["no_record_n"] == s["systems_n"] - 2
    assert set(s["counts"]) == set(c2.ct.OUTCOME_IDS)
    assert c and s["review_due_n"] == 0


def test_chain_record_and_audit_rows(v2: Console) -> None:
    seen: list[tuple[str, str, dict[str, Any]]] = []

    class Sink:
        def record(self, record_type: str, record_ref: str, payload: Any) -> str:
            seen.append((record_type, record_ref, dict(payload)))
            return "h"

    v2.ctx.classification_v2.evidence_sink = Sink()
    sid = create(v2)
    before = len(v2.ctx.tables.query("console_action"))
    decide(
        v2,
        sid,
        {
            **medium_body(),
            "answers": {
                **medium_body()["answers"],
                "N-SYSTEM": {"answer": "yes", "note": "private words", "evidence": "doc:secret-1"},
            },
        },
    )
    approve(v2, sid)
    recs = [p for t, _, p in seen if t == "classification_v2"]
    assert [p["action"] for p in recs] == ["decide", "approve"]
    for p in recs:
        assert p["outcome"] == "medium" and len(p["path_hash"]) == 64 and p["steps_n"] == 4
        assert "private words" not in str(p) and "secret-1" not in str(p) and DECIDER not in str(p)
        assert not any(isinstance(v, float) for v in p.values())
    assert recs[1]["risk_level_set"] is True and recs[0]["path_hash"] == recs[1]["path_hash"]
    new = v2.ctx.tables.query("console_action", order_by=("ts",))[before:]
    mine = [
        x
        for x in new
        if x["permission"] in ("systems.edit", "systems.approve") and x["target_id"] == sid
    ]
    assert [x["outcome"] for x in mine] == ["attempted", "ok", "attempted", "ok"]


# ============================================================ console


def page(c: Console, sid: str, lang: str = "en", user: str = DECIDER, hx: bool = False) -> Any:
    return c.get(
        f"/console/systems/{sid}/classify?lang={lang}", user=user, headers=HX if hx else {}
    )


def test_page_full_and_fragment(v2: Console) -> None:
    sid = create(v2)
    full = page(v2, sid)
    assert full.status_code == 200 and "<html" in full.text and 'id="classify-panel"' in full.text
    frag = page(v2, sid, hx=True)
    assert frag.status_code == 200 and "<html" not in frag.text
    assert 'data-classify-tree="1"' in frag.text and 'data-node="N-SYSTEM"' in frag.text
    assert "<script" not in frag.text.lower()  # the tree is drawn without a script
    assert "onclick" not in frag.text.lower() and "javascript:" not in frag.text.lower()
    for nid in ("N-SYSTEM", "N-PROHIBITED", "N-PM-LIST", "N-THRESHOLD", "N-CERT", "N-CONFUSE"):
        assert f'data-node="{nid}"' in frag.text
    assert "VN-DEC142-2026 Art. 6(2)" in frag.text  # the article of the node
    assert 'data-outcome-card="high_certify"' in frag.text
    assert 'data-trigger="NT-ROUTINE"' in frag.text and "10,000,000" in frag.text
    assert 'data-empty="current"' in frag.text


def test_page_vietnamese_and_english(v2: Console) -> None:
    sid = create(v2)
    vi = page(v2, sid, "vi", hx=True).text
    en = page(v2, sid, "en", hx=True).text
    assert "Cây phân loại" in vi and "Classification tree" in en
    assert "Hệ thống có được phát triển" in vi and "Is the system developed" in en


def test_page_unknown_system_is_a_400_message_and_viewer_is_read_only(v2: Console) -> None:
    r = page(v2, "sys-nope")  # the console answers a missing system with a 400 message
    assert r.status_code == 400 and "does not exist" in r.text
    sid = create(v2)
    assert page(v2, sid, user=VIEWER, hx=True).status_code == 404  # a scoped role: out of scope
    html = page(v2, sid, user="auditor.dung", hx=True).text
    assert 'data-action="decide"' not in html and "systems.edit" in html
    assert 'name="a_N-SYSTEM"' not in html  # no answer fields for a reader


def test_htmx_preview_decide_and_approve(v2: Console) -> None:
    sid = create(v2, user_segment="customer")
    base = f"/console/systems/{sid}/classify"
    data = {"a_N-SYSTEM": "yes", "a_N-PROHIBITED": "no", "q_Q-OTHER": "no", "qj_Q-OTHER": SHORT}
    # preview: the CONFUSE node is answered by the rule (customer-facing assistant)
    r = v2.post(base, {**data, "do": "preview"})
    assert r.status_code == 200 and "<html" not in r.text
    assert 'data-state="on"' in r.text and 'data-outcome="medium"' in r.text
    assert v2.ctx.state.query("classification_v2", {"system_id": sid}) == []
    # save
    r = v2.post(base, {**data, "do": "decide", "e_N-CONFUSE": "doc:chat-screen-3"})
    assert r.status_code == 200 and 'data-record="pending"' in r.text
    rows = v2.ctx.state.query("classification_v2", {"system_id": sid})
    assert len(rows) == 1 and rows[0]["outcome"] == "medium" and rows[0]["decided_by"] == DECIDER
    assert 'data-cannot-approve="1"' in r.text  # the decider sees that they cannot approve
    # the second person sees the approve button and uses it
    page_b = page(v2, sid, user=APPROVER, hx=True)
    assert 'data-action="approve"' in page_b.text
    r = v2.post(base + "/approve", {}, user=APPROVER)
    assert r.status_code == 200 and 'data-record="current"' in r.text
    assert system(v2, sid)["risk_level"] == "medium"
    # the same person again is refused with a flash, never a 5xx
    sid2 = create(v2, user_segment="customer")
    v2.post(f"/console/systems/{sid2}/classify", {**data, "do": "decide"}, user=APPROVER)
    r = v2.post(f"/console/systems/{sid2}/classify/approve", {}, user=APPROVER)
    assert r.status_code == 400 and "same_person" in r.text


def test_console_incomplete_decide_is_400(v2: Console) -> None:
    sid = create(v2)
    r = v2.post(f"/console/systems/{sid}/classify", {"do": "decide", "a_N-SYSTEM": "yes"})
    assert r.status_code == 400 and "incomplete_path" in r.text


def test_console_post_needs_htmx_or_same_origin(v2: Console) -> None:
    sid = create(v2)
    r = v2.post(f"/console/systems/{sid}/classify", {"do": "preview"}, htmx=False)
    assert r.status_code == 400  # a plain post without Origin is refused (CSRF guard)
    r = v2.post(
        f"/console/systems/{sid}/classify",
        {"do": "decide", "a_N-SYSTEM": "no"},
        htmx=False,
        headers={"Sec-Fetch-Site": "same-origin"},
        follow_redirects=False,
    )
    assert r.status_code == 303 and r.headers["location"].startswith(
        f"/console/systems/{sid}/classify"
    )
    assert v2.ctx.state.query("classification_v2", {"system_id": sid})[0]["outcome"] == "not_system"


def test_viewer_cannot_post_from_the_console(v2: Console) -> None:
    sid = create(v2)
    assert (
        v2.post(f"/console/systems/{sid}/classify", {"do": "preview"}, user=VIEWER).status_code
        == 403
    )
    assert v2.post(f"/console/systems/{sid}/classify/approve", {}, user=VIEWER).status_code == 403


# ============================================================ register step


@pytest.fixture
def reg(v2: Console, monkeypatch: pytest.MonkeyPatch) -> Console:
    for flag in ("console_register_v2", "console_nav_v3", "agents_api_enabled"):
        monkeypatch.setattr(v2.ctx.settings, flag, True)
    return v2


def _step4(c: Console, lang: str = "en") -> str:
    did = new(c)
    assert step(c, did, 1, S1).status_code == 200
    assert step(c, did, 2, {**S2, "user_segment": "customer"}).status_code == 200
    assert step(c, did, 3).status_code == 200
    r = c.get(f"/console/register/{did}/step/4?lang={lang}")
    assert r.status_code == 200
    return str(r.text)


def test_register_step_shows_the_drawn_tree_when_on(reg: Console) -> None:
    html = _step4(reg)
    assert 'data-register="tree-v2"' in html and 'data-classify-tree="1"' in html
    assert 'data-node="N-PM-LIST"' in html and 'data-register="proposal"' in html
    assert "<select" in html and 'name="a_Q-MONEY"' in html  # the Decision 33 form is as before
    assert 'name="a_N-SYSTEM"' not in html  # the copy is read only
    assert "Classification tree" in html
    vi = _step4(reg, "vi")
    assert "Cây phân loại" in vi


def test_register_step_unchanged_when_off(on: Console, monkeypatch: pytest.MonkeyPatch) -> None:
    for flag in ("console_register_v2", "console_nav_v3", "agents_api_enabled"):
        monkeypatch.setattr(on.ctx.settings, flag, True)
    assert on.ctx.settings.classification_v2 is False
    html = _step4(on)
    assert 'data-register="proposal"' in html and 'data-register="step4"' in html
    assert "tree-v2" not in html and "data-classify-tree" not in html

# ruff: noqa: F811  (pytest fixtures are imported and then named as arguments)
"""WP-G1: API and console routes: the off path, RBAC, 400 not 500, HTMX fragments, audit rows."""

from __future__ import annotations

from typing import Any

import pytest

from supervisor.core import rbac
from supervisor.guardian_factory.author import Author

from .conftest import FakeChat, adapters, console, gf, regex_def, seeded  # noqa: F401  (fixtures)

AN = "reviewer.an"  # reviewer: in the data group
EM = "approver.em"  # approver: not in the data group
HOA = "viewer.hoa"
CHI = "admin.chi"
HX = {"HX-Request": "true"}


def api(c: Any, method: str, url: str, body: Any = None, user: str = AN) -> Any:
    return c.client.request(method, url, json=body, headers={"X-Dev-User": user})


def make(c: Any, **over: Any) -> dict[str, Any]:
    r = api(c, "POST", "/v1/guardian-defs", regex_def(**over))
    assert r.status_code == 201, r.text
    return r.json()


FORM = {
    "name": "Account numbers",
    "description": "d",
    "owner_group": "data",
    "type": "regex",
    "stage": "input",
    "action_on_fail": "redact",
    "sensitivity": "2",
    "scope_agents": "*",
    "scope_tools": "*",
    "scope_data_classes": "",
    "benchmark_pack": "",
    "min_tpr_pct": "90",
    "max_fpr_pct": "5",
    "max_p95_ms": "50",
    "shadow_days": "0",
    "config_json": '{"pattern": "\\\\d{9,14}", "mask_token": "<ACCOUNT>"}',
}

OFF_ROUTES = [
    ("GET", "/v1/guardian-defs"),
    ("POST", "/v1/guardian-defs"),
    ("GET", "/v1/guardian-defs/x"),
    ("POST", "/v1/guardian-defs/x"),
    ("POST", "/v1/guardian-defs/x/draft-artifact"),
    ("POST", "/v1/guardian-defs/x/retire"),
    ("POST", "/v1/guardian-defs/x/reopen"),
    ("POST", "/v1/guardian-defs/x/new-version"),
    ("GET", "/v1/guardian-defs-schema"),
    ("GET", "/console/guardian-factory"),
    ("GET", "/console/guardian-factory/x"),
    ("POST", "/console/guardian-factory/x"),
    ("POST", "/console/guardian-factory/x/draft"),
    ("POST", "/console/guardian-factory/x/retire"),
    ("POST", "/console/guardian-factory/x/reopen"),
    ("POST", "/console/guardian-factory/x/new-version"),
]


# ============================================================ off path


def test_flag_default_off(console: Any) -> None:
    assert console.ctx.settings.guardian_factory is False


def test_off_every_route_answers_400_and_reads_no_table(
    console: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls: list[str] = []
    orig_q, orig_g = console.ctx.state.query, console.ctx.state.get

    def spy_q(table: str, *a: Any, **k: Any) -> Any:
        calls.append(table)
        return orig_q(table, *a, **k)

    def spy_g(table: str, *a: Any, **k: Any) -> Any:
        calls.append(table)
        return orig_g(table, *a, **k)

    monkeypatch.setattr(console.ctx.state, "query", spy_q)
    monkeypatch.setattr(console.ctx.state, "get", spy_g)
    for method, path in OFF_ROUTES:
        r = console.client.request(
            method,
            path,
            json={} if path.startswith("/v1") else None,
            headers={"X-Dev-User": AN, **HX},
        )
        assert r.status_code == 400, (method, path, r.status_code)
        assert "guardian_factory_off" in r.text, (method, path)
        assert 'id="gf-list"' not in r.text and 'id="gf-editor"' not in r.text
    assert not [t for t in calls if t.startswith("guardian_def")], calls


def test_detectors_off_also_turns_it_off(console: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(console.ctx.settings, "guardian_factory", True)
    monkeypatch.setattr(console.ctx.settings, "detectors_enabled", False)
    r = api(console, "GET", "/v1/guardian-defs")
    assert r.status_code == 400 and "guardian_factory_off" in r.text


# ============================================================ JSON API


def test_create_get_list_and_schema(gf: Any) -> None:
    out = make(gf)
    assert out["id"] == "account-numbers" and out["state"] == "draft"
    r = api(gf, "GET", "/v1/guardian-defs/account-numbers")
    assert r.status_code == 200 and r.json()["definition"]["type"] == "regex"
    r = api(gf, "GET", "/v1/guardian-defs?state=draft&owner_group=data")
    assert [i["id"] for i in r.json()["items"]] == ["account-numbers"]
    assert r.json()["counts"]["draft"] == 1
    assert (
        api(gf, "GET", "/v1/guardian-defs?colour=red").status_code == 200
    )  # unknown query ignored
    assert api(gf, "GET", "/v1/guardian-defs/missing").status_code == 404
    assert api(gf, "GET", "/v1/guardian-defs/account-numbers?version=abc").status_code == 400
    s = api(gf, "GET", "/v1/guardian-defs-schema").json()
    assert "x-config-by-type" in s


def test_validation_is_400_naming_the_field(gf: Any) -> None:
    r = api(gf, "POST", "/v1/guardian-defs", regex_def(config={"pattern": "(a+)+b"}))
    assert r.status_code == 400 and "config.pattern" in r.json()["error"]
    r = api(gf, "POST", "/v1/guardian-defs", regex_def(type="judge_prompt", action_on_fail="block"))
    assert r.status_code == 400 and "action_on_fail" in r.json()["error"]
    for raw in (b"[1]", b"{oops"):
        r = gf.client.post("/v1/guardian-defs", content=raw, headers={"X-Dev-User": AN})
        assert r.status_code == 400
    r = api(gf, "POST", "/v1/guardian-defs", {"id": "x"})
    assert r.status_code == 400  # missing fields: a message, never a 500


def test_save_retire_reopen_new_version(gf: Any) -> None:
    make(gf)
    r = api(gf, "POST", "/v1/guardian-defs/account-numbers", regex_def(name="Renamed"))
    assert r.status_code == 200 and r.json()["name"] == "Renamed"
    r = api(gf, "POST", "/v1/guardian-defs/account-numbers/retire")
    assert r.status_code == 200 and r.json()["state"] == "retired"
    assert api(gf, "POST", "/v1/guardian-defs/account-numbers/retire").status_code == 400
    assert api(gf, "POST", "/v1/guardian-defs/account-numbers", regex_def()).status_code == 400
    r = api(gf, "POST", "/v1/guardian-defs/account-numbers/new-version")
    assert r.json()["version"] == 2
    assert api(gf, "POST", "/v1/guardian-defs/nope/retire").status_code == 404


def test_later_states_are_not_reachable(gf: Any) -> None:
    from supervisor.guardian_factory.store import check_transition

    make(gf)
    with pytest.raises(Exception, match="not allowed yet"):
        check_transition("draft", "benchmarked")


def test_draft_artifact_stores_nothing(gf: Any) -> None:
    r = api(
        gf,
        "POST",
        "/v1/guardian-defs/account-numbers/draft-artifact",
        {"type": "regex", "text": "Hide the bank account number"},
    )
    assert r.status_code == 200
    assert r.json()["library_id"] == "account_number" and r.json()["saved"] is False
    assert gf.ctx.state.query("guardian_def", {}) == []
    # no model configured: the model path says so, with a 400
    r = api(gf, "POST", "/v1/guardian-defs/x/draft-artifact", {"type": "policy", "text": "p"})
    assert r.status_code == 400 and "model not configured" in r.json()["error"]
    r = api(gf, "POST", "/v1/guardian-defs/x/draft-artifact", {"type": "regex"})
    assert r.status_code == 400
    r = api(
        gf, "POST", "/v1/guardian-defs/x/draft-artifact", {"type": "regex", "text": "a", "z": 1}
    )
    assert r.status_code == 400


def test_draft_artifact_with_a_fake_model_and_a_bad_answer(
    gf: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    good = FakeChat({"config": {"pattern": r"ZX\d{4,8}"}})
    monkeypatch.setattr(gf.ctx, "_guardian_author", Author(chat=good), raising=False)
    body = {"type": "regex", "text": "references starting with ZX"}
    r = api(gf, "POST", "/v1/guardian-defs/x/draft-artifact", body)
    assert r.status_code == 200 and r.json()["source"] == "model"
    bad = FakeChat({"config": {"pattern": "(a+)+b"}})
    monkeypatch.setattr(gf.ctx, "_guardian_author", Author(chat=bad), raising=False)
    r = api(gf, "POST", "/v1/guardian-defs/x/draft-artifact", body)
    assert r.status_code == 400 and "config.pattern" in r.json()["error"]


# ============================================================ RBAC


def test_viewer_reads_but_cannot_write(gf: Any) -> None:
    make(gf)
    assert api(gf, "GET", "/v1/guardian-defs", user=HOA).status_code == 200
    assert api(gf, "GET", "/console/guardian-factory", user=HOA).status_code == 200
    for method, path in (
        ("POST", "/v1/guardian-defs"),
        ("POST", "/v1/guardian-defs/account-numbers"),
        ("POST", "/v1/guardian-defs/account-numbers/retire"),
        ("POST", "/v1/guardian-defs/account-numbers/draft-artifact"),
    ):
        assert api(gf, method, path, regex_def(), user=HOA).status_code == 403, path


def test_only_group_members_edit_their_group(gf: Any) -> None:
    make(gf)
    assert (
        api(gf, "POST", "/v1/guardian-defs/account-numbers", regex_def(), user=EM).status_code
        == 403
    )
    assert api(gf, "POST", "/v1/guardian-defs/account-numbers/retire", user=EM).status_code == 403
    assert (
        api(
            gf, "POST", "/v1/guardian-defs", regex_def(id="l", owner_group="legal"), user=EM
        ).status_code
        == 201
    )
    r = api(gf, "POST", "/v1/guardian-defs/account-numbers", regex_def(name="Admin"), user=CHI)
    assert r.status_code == 200
    # every group's guardians are readable by any viewer
    assert {i["id"] for i in api(gf, "GET", "/v1/guardian-defs", user=HOA).json()["items"]} == {
        "account-numbers",
        "l",
    }


def test_permissions_and_route_rows_exist() -> None:
    assert "viewer" in rbac.PERMISSIONS["guardians.view"][0]
    assert "viewer" not in rbac.PERMISSIONS["guardians.edit"][0]
    assert rbac.ROUTES[("POST", "/v1/guardian-defs/{def_id}/retire")] == "guardians.edit"
    assert rbac.ROUTES[("GET", "/console/guardian-factory/{def_id}")] == "guardians.view"


# ============================================================ console


def test_registry_page_and_fragment(gf: Any) -> None:
    make(gf)
    make(
        gf,
        id="kw",
        type="keyword_list",
        config={"words": ["a"]},
        owner_group="legal",
        stage="output",
    )
    r = gf.get("/console/guardian-factory")
    assert r.status_code == 200 and "<html" in r.text and 'id="gf-list"' in r.text
    assert "account-numbers" in r.text and "kw" in r.text
    r = gf.get("/console/guardian-factory?owner_group=legal", headers=HX)
    assert r.status_code == 200 and "<html" not in r.text
    assert 'data-def="kw"' in r.text and 'data-def="account-numbers"' not in r.text
    r = gf.get("/console/guardian-factory?type=regex&stage=input", headers=HX)
    assert 'data-def="account-numbers"' in r.text and 'data-def="kw"' not in r.text
    r = gf.get("/console/guardian-factory?state=retired", headers=HX)
    assert 'data-def="' not in r.text


def test_editor_page_new_and_existing(gf: Any) -> None:
    r = gf.get("/console/guardian-factory/new")
    assert r.status_code == 200 and "Draft the artifact" in r.text and 'id="gf-editor"' in r.text
    assert 'data-panel="benchmark"' in r.text and 'data-panel="shadow"' in r.text
    make(gf)
    r = gf.get("/console/guardian-factory/account-numbers", headers=HX)
    assert "<html" not in r.text and "&lt;ACCOUNT&gt;" in r.text and 'data-state="draft"' in r.text
    assert gf.get("/console/guardian-factory/missing").status_code == 404
    r = gf.get("/console/guardian-factory/account-numbers", user=HOA, headers=HX)
    assert 'data-view-only="1"' in r.text and "<fieldset disabled>" in r.text.replace("\n", "")


def test_console_draft_fills_the_artifact_box_and_saves_nothing(gf: Any) -> None:
    r = gf.post(
        "/console/guardian-factory/new/draft",
        {**FORM, "name": "", "config_json": "{}", "text": "Hide the phone number of the customer"},
    )
    assert r.status_code == 200 and 'data-draft="library"' in r.text
    assert "phone" in r.text.lower() and "Nothing is saved" in r.text
    assert "&lt;PHONE&gt;" in r.text
    assert gf.ctx.state.query("guardian_def", {}) == []


def test_console_draft_shows_the_over_broad_flag(gf: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    chat = FakeChat({"config": {"pattern": r"\d+"}})
    monkeypatch.setattr(gf.ctx, "_guardian_author", Author(chat=chat), raising=False)
    r = gf.post("/console/guardian-factory/new/draft", {**FORM, "text": "match numbers"})
    assert r.status_code == 200 and "data-over-broad" in r.text


def test_console_draft_refusal_is_a_400_message(gf: Any) -> None:
    r = gf.post("/console/guardian-factory/new/draft", {**FORM, "type": "policy", "text": "x"})
    assert r.status_code == 400 and "model not configured" in r.text


def test_console_create_save_retire_reopen(gf: Any) -> None:
    r = gf.post("/console/guardian-factory/new", {**FORM, "id": "from-form"})
    assert r.status_code == 200 and r.headers["HX-Redirect"].startswith(
        "/console/guardian-factory/from-form"
    )
    assert (
        gf.ctx.state.get("guardian_def", {"def_id": "from-form", "version": 1})["state"] == "draft"
    )
    r = gf.post("/console/guardian-factory/from-form", {**FORM, "name": "Changed"})
    assert r.status_code == 200 and "Changed" in r.text and "from-form: saved" in r.text
    r = gf.post("/console/guardian-factory/from-form/retire", {})
    assert r.status_code == 200 and 'data-state="retired"' in r.text
    assert 'data-action="reopen"' in r.text and 'data-action="new-version"' in r.text
    r = gf.post("/console/guardian-factory/from-form/reopen", {})
    assert 'data-state="draft"' in r.text and 'data-history="1"' in r.text
    r = gf.post("/console/guardian-factory/from-form/retire", {}, user=EM)
    assert r.status_code == 403


def test_console_validation_names_the_field(gf: Any) -> None:
    r = gf.post(
        "/console/guardian-factory/new",
        {**FORM, "id": "bad", "config_json": '{"pattern": "(a+)+b"}'},
    )
    assert r.status_code == 400 and "config.pattern" in r.text
    r = gf.post("/console/guardian-factory/new", {**FORM, "id": "bad", "config_json": "{nope"})
    assert r.status_code == 400 and "config" in r.text
    r = gf.post("/console/guardian-factory/new", {**FORM, "id": "bad", "sensitivity": "high"})
    assert r.status_code == 400 and "sensitivity" in r.text
    r = gf.post(
        "/console/guardian-factory/new",
        {
            **FORM,
            "id": "bad",
            "type": "classifier",
            "config_json": '{"model_ref": "guard_model", "threshold_bp": 10}',
        },
    )
    assert r.status_code == 400 and "action_on_fail" in r.text


def test_console_posts_need_htmx_or_same_origin(gf: Any) -> None:
    r = gf.post("/console/guardian-factory/new", {**FORM, "id": "csrf"}, htmx=False)
    assert r.status_code == 400
    assert gf.ctx.state.query("guardian_def", {}) == []


def test_audit_rows_two_per_post(gf: Any) -> None:
    make(gf)
    gf.post("/console/guardian-factory/account-numbers/retire", {})
    rows = [
        x
        for x in gf.ctx.tables.query("console_action", order_by=("ts",))
        if x["permission"] == "guardians.edit"
    ]
    assert [x["outcome"] for x in rows] == ["attempted", "ok", "attempted", "ok"]
    assert len({x["request_id"] for x in rows}) == 2


def test_i18n_keys_exist_in_both_languages(gf: Any) -> None:
    from supervisor.console.i18n_guardian_factory import GF

    assert GF and all(len(v) == 2 and v[0] and v[1] for v in GF.values())
    r = gf.get("/console/guardian-factory/new?lang=vi")
    assert "Xưởng tạo guardian" in r.text and "Soạn bản nháp" in r.text

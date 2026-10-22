"""WP-UX4b: the register wizard at /console/systems/new.

The wizard applies nothing. Step 2 (preliminary checks) writes nothing; step 3 registers a
draft and opens the initiation tasks. Bad input is HTTP 400 with the reason."""

from __future__ import annotations

import sys
import types
from typing import Any

import pytest

from supervisor.console import systems_wizard
from supervisor.governance import model as gm

from .conftest import Console, person

HX = {"HX-Request": "true"}
OWNER_USER = "payops-lead@example.invalid"
FORM = {
    "name": "Wizard system",
    "owner_team": "payments-team",
    "purpose": "Answers staff questions about domestic transfers.",
    "system_type": "assistant",
    "org_role": "deployer",
    "user_segment": "internal",
    "personal_data": "pseudonymised",
    "human_control": "post_review",
}
CHECKS = "/console/systems/new/checks"
REPO = "tests/onboard/data/artifact_credit_memo"


@pytest.fixture
def v3(on: Console, monkeypatch: pytest.MonkeyPatch) -> Console:
    monkeypatch.setattr(on.ctx.settings, "console_nav_v3", True)
    return on


def counts(c: Console) -> tuple[int, int, int]:
    return (
        len(c.ctx.state.query("ai_system")),
        len(c.ctx.state.query("task")),
        len(c.ctx.state.query("system_team")),
    )


# ------------------------------------------------------------------ step 1


@pytest.mark.parametrize("lang", ["en", "vi"])
def test_form_page_renders(v3: Console, lang: str) -> None:
    r = v3.get(f"/console/systems/new?lang={lang}")
    assert r.status_code == 200
    for name in ("name", "owner_team", "purpose", "system_type", "org_role", "user_segment"):
        assert f'name="{name}"' in r.text
    assert 'name="money_movement"' in r.text and 'name="repo_path"' in r.text
    assert 'action="/console/systems/new/checks' in r.text
    assert 'name="autonomy_level"' not in r.text  # no such column without WP-G2
    if lang == "vi":
        assert "Đăng ký hệ thống AI" in r.text


def test_systems_page_links_to_the_wizard(v3: Console) -> None:
    html = v3.get("/console/systems?lang=en").text
    assert 'data-wizard="link"' in html and "/console/systems/new" in html
    assert 'data-wizard="link"' not in v3.get("/console/systems", user="viewer.hoa").text


def test_viewer_cannot_open_the_wizard(v3: Console) -> None:
    assert v3.get("/console/systems/new", user="viewer.hoa").status_code == 403
    assert v3.post(CHECKS, FORM, user="viewer.hoa").status_code == 403
    assert v3.post("/console/systems/new", FORM, user="viewer.hoa").status_code == 403
    assert counts(v3) == (0, 0, 0)


def test_autonomy_choice_appears_only_when_the_field_exists(
    v3: Console, monkeypatch: pytest.MonkeyPatch
) -> None:
    assert systems_wizard.autonomy_choices() == ()
    monkeypatch.setattr(gm, "EDITABLE", (*gm.EDITABLE, "autonomy_level"))  # what WP-G2 adds
    assert len(systems_wizard.autonomy_choices()) == 6
    html = v3.get("/console/systems/new?lang=en").text
    assert 'name="autonomy_level"' in html and "L3 Uses tools, supervised" in html


# ------------------------------------------------------------------ step 2: the checks


def test_checks_page_shows_proposals_and_writes_nothing(v3: Console) -> None:
    form = {**FORM, "money_movement": "1", "human_control": "post_review"}
    before = counts(v3)
    r = v3.post(CHECKS, form)
    assert r.status_code == 200, r.text[:300]
    html = r.text
    assert counts(v3) == before == (0, 0, 0)
    # proposal, not applied
    assert "Nothing is applied." in html and 'data-wizard="proposals"' in html
    assert (
        'data-num="class"' in html and "High risk" in html and "proposed risk level: High" in html
    )
    assert "Because of" in html and "Moves money" in html
    # no folder: the readiness figure is not available, with the reason
    assert 'data-num="readiness"' in html and "not available" in html
    assert "No repository folder was given." in html
    # packs for the declared system, from the real manifests
    packs = systems_wizard.packs_for(
        {
            "system_type": "assistant",
            "personal_data": "pseudonymised",
            "credit_decision": False,
        }
    )
    assert packs["rows"] and not packs["na"]
    for p in packs["rows"]:
        assert p["id"] in html
    # the floor needs WP-G2
    assert 'data-num="floor"' in html and "rules engine is not installed" in html
    # the confirm form carries the draft
    assert 'data-wizard="confirm"' in html and 'name="money_movement" value="1"' in html
    assert 'name="name" value="Wizard system"' in html


def test_checks_class_follows_the_declared_fields(v3: Console) -> None:
    lo = v3.post(
        CHECKS, {**FORM, "name": "Low one", "money_movement": "1", "human_control": "pre_approval"}
    )
    assert lo.status_code == 200 and "Not high risk" in lo.text
    assert "no level proposed; a person sets it" in lo.text
    hi = v3.post(
        CHECKS, {**FORM, "name": "Credit one", "credit_decision": "1", "human_control": "none"}
    )
    assert "High risk" in hi.text and "Takes credit decisions" in hi.text
    assert counts(v3) == (0, 0, 0)


def test_checks_vi(v3: Console) -> None:
    r = v3.post(CHECKS + "?lang=vi", FORM)
    assert r.status_code == 200 and "Kiểm tra sơ bộ" in r.text and "Chưa áp dụng gì." in r.text


def test_readiness_advisor_runs_in_process_on_a_folder(v3: Console) -> None:
    from supervisor.advisory.integration.advise import advise
    from supervisor.console.onboard_runs import resolve_target

    expected = advise(resolve_target(REPO), chat=None).report.readiness
    r = v3.post(CHECKS, {**FORM, "repo_path": REPO})
    assert r.status_code == 200, r.text[:300]
    assert f"{expected.total} / 100" in r.text
    band = systems_wizard.band_of(expected.total)
    assert {
        "ux4b_band_ready": "Ready for shadow onboarding",
        "ux4b_band_patches": "Needs the patches",
        "ux4b_band_work": "Needs work first",
    }[band] in r.text
    for a in expected.areas:
        assert f"{a.points} / {a.weight}" in r.text
    assert counts(v3) == (0, 0, 0)


def test_bands_follow_the_rubric() -> None:
    assert systems_wizard.band_of(100) == systems_wizard.band_of(80) == "ux4b_band_ready"
    assert systems_wizard.band_of(79) == systems_wizard.band_of(50) == "ux4b_band_patches"
    assert systems_wizard.band_of(49) == systems_wizard.band_of(0) == "ux4b_band_work"


def test_bad_folder_and_missing_right_are_400(v3: Console) -> None:
    for path, text in [
        ("no/such/folder", "folder not found"),
        ("x" * 600, "too long"),
        ("/", "folder"),
    ]:
        r = v3.post(CHECKS, {**FORM, "repo_path": path})
        assert r.status_code == 400 and text in r.text, path
    with pytest.raises(Exception, match="right to start onboarding"):
        systems_wizard.readiness(person("v", "viewer"), REPO)


@pytest.mark.parametrize(
    ("over", "text"),
    [
        ({"system_type": "robot"}, "system_type"),
        ({"name": ""}, "required"),
        ({"owner_team": ""}, "required"),
        ({"purpose": "x" * 2100}, "purpose"),
        ({"personal_data": "all"}, "personal_data"),
        ({"owner_user": "bad user!"}, "owner_user"),
    ],
)
def test_checks_refuse_bad_input_with_400(v3: Console, over: dict[str, str], text: str) -> None:
    r = v3.post(CHECKS, {**FORM, **over})
    assert r.status_code == 400 and "msg-error" in r.text and text in r.text
    assert counts(v3) == (0, 0, 0)


def test_checks_refuse_a_name_already_used(v3: Console) -> None:
    assert v3.post("/console/systems/new", FORM).status_code == 200
    r = v3.post(CHECKS, FORM)
    assert r.status_code == 400 and "already" in r.text


def test_scoping_rules_apply_before_the_checks(v3: Console) -> None:
    # a scoped owner may use only a team they already work in
    r = v3.post(CHECKS, {**FORM, "owner_team": "risk-team"}, user=OWNER_USER)
    assert r.status_code == 400 and "owner_team" in r.text
    page = v3.get("/console/systems/new?lang=en", user=OWNER_USER).text
    assert 'data-wizard="scope"' in page and "Payments Ops" in page
    ok = v3.post(
        CHECKS,
        {**FORM, "owner_team": "Payments Ops", "owner_user": "someone.else"},
        user=OWNER_USER,
    )
    assert ok.status_code == 200
    assert (
        'name="owner_user" value="payops-lead@example.invalid"' in ok.text
    )  # forced to the caller
    assert 'data-wizard="scope"' not in v3.get("/console/systems/new", user="reviewer.an").text


# ------------------------------------------------------------------ step 3: register


def test_confirm_registers_a_draft_and_opens_the_initiation_tasks(v3: Console) -> None:
    form = {**FORM, "money_movement": "1", "human_control": "none"}
    r = v3.post("/console/systems/new", form)
    assert r.status_code == 200
    url = r.headers["HX-Redirect"]
    assert url.startswith("/console/systems/sys_") and url.endswith("?tab=tasks")
    sid = url.split("?")[0].rsplit("/", 1)[1]
    row = v3.ctx.state.get("ai_system", {"system_id": sid})
    # nothing was applied: a draft in initiation, class and level untouched
    assert row["status"] == "draft" and row["lifecycle_stage"] == "initiation"
    assert row["decision33_class"] == "unclassified" and row["risk_level"] == "unspecified"
    assert row["owner_user"] == "reviewer.an"
    tasks = v3.ctx.state.query("task", {"agent_id": sid})
    assert sorted(t["template_id"] for t in tasks) == ["SYS-INTAKE-CHECKS", "SYS-INTAKE-CONFIRM"]
    assert all(t["stage"] == "initiation" and t["required"] for t in tasks)
    # the Tasks tab of the system shows them
    page = v3.get(url).text
    assert "Confirm the intake answers" in page and "Review the preliminary checks" in page
    # audit: attempted then ok, with a system target; the chain has the create record
    rows = [
        x
        for x in v3.ctx.tables.query("console_action", order_by=("ts",))
        if x["permission"] == "systems.edit"
    ]
    assert [x["outcome"] for x in rows] == ["attempted", "ok"] and rows[1][
        "target_kind"
    ] == "system"


def test_confirm_plain_post_needs_the_origin_and_redirects(v3: Console) -> None:
    assert v3.post("/console/systems/new", FORM, htmx=False).status_code == 400
    r = v3.post(
        "/console/systems/new",
        FORM,
        htmx=False,
        headers={"Origin": "http://testserver"},
        follow_redirects=False,
    )
    assert r.status_code == 303 and r.headers["location"].startswith("/console/systems/sys_")


def test_confirm_refuses_bad_input_and_a_duplicate(v3: Console) -> None:
    bad = v3.post("/console/systems/new", {**FORM, "human_control": "maybe"})
    assert bad.status_code == 400 and "human_control" in bad.text
    assert v3.post("/console/systems/new", FORM).status_code == 200
    dup = v3.post("/console/systems/new", FORM)
    assert dup.status_code == 400 and "already" in dup.text
    assert counts(v3)[0] == 1


def test_tasks_are_opened_once(v3: Console) -> None:
    sid = v3.ctx.systems.register({**FORM, "owner_user": "reviewer.an"}, "reviewer.an")["system_id"]
    assert len(systems_wizard.open_tasks(v3.ctx, sid, "reviewer.an")) == 2
    assert systems_wizard.open_tasks(v3.ctx, sid, "reviewer.an") == []
    assert len(v3.ctx.state.query("task", {"agent_id": sid})) == 2


# ------------------------------------------------------------------ WP-G2 guards


def test_g2_rules_and_classification_are_used_when_present(
    v3: Console, monkeypatch: pytest.MonkeyPatch
) -> None:
    seen: list[dict[str, Any]] = []

    def evaluate(system: dict[str, Any]) -> Any:
        seen.append(system)
        return types.SimpleNamespace(
            guardian_floor=[
                {"slug": "dlp_vn", "rule": "AR-PDPL"},
                {"slug": "inline_redaction", "rule": "AR-PDPL"},
            ]
        )

    rules = types.ModuleType("supervisor.governance.rules")
    rules.evaluate = evaluate  # type: ignore[attr-defined]
    cls = types.ModuleType("supervisor.governance.classification")
    cls.propose = lambda system: {"outcome": "high_risk"}  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "supervisor.governance.rules", rules)
    monkeypatch.setitem(sys.modules, "supervisor.governance.classification", cls)
    html = v3.post(CHECKS, {**FORM, "human_control": "pre_approval"}).text
    assert "<code>dlp_vn</code>" in html and "AR-PDPL" in html
    assert "from the classification rules" in html and "High risk" in html  # rules beat declared
    assert seen and seen[0]["name"] == "Wizard system"
    assert "rules engine is not installed" not in html


def test_a_failing_g2_module_does_not_stop_the_wizard(
    v3: Console, monkeypatch: pytest.MonkeyPatch
) -> None:
    def boom(system: dict[str, Any]) -> Any:
        raise RuntimeError("rules broke")

    rules = types.ModuleType("supervisor.governance.rules")
    rules.evaluate = boom  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "supervisor.governance.rules", rules)
    r = v3.post(CHECKS, FORM)
    assert r.status_code == 200 and "rules engine is not installed" in r.text

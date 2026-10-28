"""WP-F3 (phase 12B): the gate panel, the simulation review page and the promotion routes.

Off path first: every route answers 400 factory_gate_off and no gate table is read. Then the panel
as htmx fragments, a run started from the console (a background job joined by the test), the
promotion buttons with the roles of config/users.yaml, the two audit rows of each POST, the
catalogue card, the simulation review and the RBAC matrix. The ChatModel is a test double; the
product has no mock path."""

from __future__ import annotations

import json
import re
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from supervisor.adapters.auth.base import AuthPrincipal
from supervisor.factory import caps, gate, golden, probe
from tests.factory.f3_helpers import FakeChat, golden_cases, load_golden

from .conftest import Console

HX = {"HX-Request": "true"}


@pytest.fixture
def on(console: Console, monkeypatch: pytest.MonkeyPatch) -> Console:
    s = console.ctx.settings
    for flag in ("governance_enabled", "agent_factory", "agent_factory_gate"):
        monkeypatch.setattr(s, flag, True)
    console.ctx.gate_chat = FakeChat()  # type: ignore[attr-defined]
    return console


def create(
    c: Console, agent_id: str = "mr-agent", user: str = "reviewer.an", dim: str = "model"
) -> Any:
    return c.post(
        "/console/factory/new", {"dimension_id": dim, "id": agent_id, "name": "Mine"}, user
    )


def row(c: Console, agent_id: str = "mr-agent", version: str = "0.1") -> dict[str, Any]:
    r = dict(c.ctx.state.get("factory_agent", {"id": agent_id, "version": version}))
    r["definition"] = (
        json.loads(r["definition_json"])
        if isinstance(r["definition_json"], str)
        else r["definition_json"]
    )
    return r


def seed(c: Console, agent_id: str = "mr-agent", labels: int = 24) -> None:
    shim = SimpleNamespace(data_dir=Path(c.ctx.settings.data_dir))
    load_golden(shim, row(c, agent_id), labels=labels)  # type: ignore[arg-type]


def start(
    c: Console, kind: str, user: str = "reviewer.an", agent_id: str = "mr-agent", **f: str
) -> Any:
    r = c.post(f"/console/factory/{agent_id}/gate/run", {"version": "0.1", "kind": kind, **f}, user)
    gate.join(agent_id)
    return r


def actions(c: Console, path: str) -> list[dict]:
    return [r for r in c.ctx.tables.query("console_action", order_by=("ts",)) if r["path"] == path]


def make_tested(c: Console, agent_id: str = "mr-agent", user: str = "reviewer.an") -> None:
    assert create(c, agent_id, user).status_code == 200
    seed(c, agent_id)
    assert start(c, "full", user, agent_id).status_code == 200
    assert row(c, agent_id)["state"] == "tested"


def promote(c: Console, action: str, user: str, agent_id: str = "mr-agent", **f: str) -> Any:
    return c.post(f"/console/factory/{agent_id}/promote/{action}", {"version": "0.1", **f}, user)


# ------------------------------------------------------------------------------ off path


def test_flag_defaults_off(console: Console) -> None:
    assert console.ctx.settings.agent_factory_gate is False


GATE_GETS = (
    "/console/factory/mr-agent/gate",
    "/console/factory/mr-agent/gate/gate_00000000000000000000",
    "/console/factory/mr-agent/simulation/gate_00000000000000000000",
    "/v1/factory/agents/mr-agent/gate",
    "/v1/factory/gate/gate_00000000000000000000",
)
GATE_POSTS = (
    "/console/factory/mr-agent/gate/run",
    "/console/factory/mr-agent/simulation/gate_00000000000000000000/mark",
    *(
        f"/console/factory/mr-agent/promote/{a}"
        for a in ("submit", "approve", "reject", "activate", "reopen", "rollback")
    ),
)


def test_off_every_route_is_400_and_no_gate_table_is_read(
    console: Console, monkeypatch: pytest.MonkeyPatch
) -> None:
    seen: list[str] = []
    real_q, real_g, real_t = (
        console.ctx.state.query,
        console.ctx.state.get,
        console.ctx.tables.query,
    )

    def spy(real: Any) -> Any:
        def inner(table: str, *a: Any, **k: Any) -> Any:
            seen.append(table)
            return real(table, *a, **k)

        return inner

    monkeypatch.setattr(console.ctx.state, "query", spy(real_q))
    monkeypatch.setattr(console.ctx.state, "get", spy(real_g))
    monkeypatch.setattr(console.ctx.tables, "query", spy(real_t))
    for flags in ({}, {"agent_factory": True, "governance_enabled": True}):  # also with F2 on
        for k, v in flags.items():
            monkeypatch.setattr(console.ctx.settings, k, v)
        for url in GATE_GETS:
            r = (
                console.get(url, "admin.chi")
                if url.startswith("/console")
                else console.client.get(url, headers={"X-Dev-User": "admin.chi"})
            )
            assert r.status_code == 400 and "factory_gate_off" in r.text, url
        for url in GATE_POSTS:
            r = console.post(url, {}, "admin.chi")
            assert r.status_code == 400 and "factory_gate_off" in r.text, url
    assert "gate_run" not in seen


def test_off_the_catalogue_and_the_editor_are_unchanged(
    console: Console, monkeypatch: pytest.MonkeyPatch
) -> None:
    for flag in ("governance_enabled", "agent_factory"):
        monkeypatch.setattr(console.ctx.settings, flag, True)
    assert create(console).status_code == 200
    page = console.get("/console/factory").text
    assert 'data-last-gate="none"' in page and "data-live-version" not in page
    editor = console.get("/console/factory/mr-agent").text
    assert 'data-step-link="gate"' not in editor
    r = console.get("/console/factory/mr-agent/step/gate")
    assert r.status_code == 400 and "bad_step" in r.text
    golden_step = console.get("/console/factory/mr-agent/step/golden").text
    assert "upload-labels" not in golden_step


def test_gate_needs_the_factory_flag_too(console: Console, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(console.ctx.settings, "agent_factory_gate", True)
    monkeypatch.setattr(console.ctx.settings, "agent_factory", False)
    assert "factory_gate_off" in console.get("/console/factory/mr-agent/gate").text


# ------------------------------------------------------------------------------ the panel


def test_editor_has_the_gate_step_and_the_panel_shows_the_golden_state(on: Console) -> None:
    create(on)
    editor = on.get("/console/factory/mr-agent").text
    assert 'data-step-link="gate"' in editor and "10. " in editor
    frag = on.get("/console/factory/mr-agent/step/gate", headers=HX).text
    assert 'data-step="gate"' in frag and 'data-gate-golden="1"' in frag
    assert "too_few_cases: 0 of 50" in frag and 'data-act="run-full"' in frag
    assert 'data-table="gate-runs"' in frag and "No gate run yet" in frag
    assert 'data-tier="high"' in frag and 'data-approval="owner_lead"' in frag
    assert 'data-act="submit"' not in frag  # a draft cannot be submitted


def test_a_viewer_sees_the_panel_without_buttons(on: Console) -> None:
    create(on)
    frag = on.get("/console/factory/mr-agent/step/gate", "viewer.hoa", headers=HX).text
    assert (
        'data-step="gate"' in frag
        and 'data-act="run-full"' not in frag
        and 'data-readonly="1"' in frag
    )


def test_golden_step_takes_gate_cases_and_labels(on: Console) -> None:
    create(on)
    shim = SimpleNamespace(data_dir=Path(on.ctx.settings.data_dir))
    cases = golden.check_gate_cases(
        golden_cases(row(on)["definition"], 50),
        [c["id"] for c in row(on)["definition"]["checklist"]],
    )[0]
    body = json.dumps({"cases": cases}).encode()
    r = on.client.post(
        "/console/factory/mr-agent/golden",
        data={"version": "0.1"},
        files={"file": ("cases.json", body, "application/json")},
        headers={"X-Dev-User": "reviewer.an", **HX},
    )
    assert r.status_code == 200 and "50 case(s) stored, 0 refused" in r.text
    assert len(golden.load_gate_cases(shim.data_dir, "mr-agent")) == 50
    assert 'data-gate-cases="50"' in r.text
    labels = [
        {
            "case_id": cases[i]["case_id"],
            "finding_id": f"f-{next(iter(cases[i]['expected']))}",
            "human_verdict": "pass",
            "label_by": "reviewer.binh",
            "labelled_at": "2026-10-20T08:00:00Z",
        }
        for i in range(21)
    ] + [
        {
            "case_id": "zzz",
            "finding_id": "f-MR-01",
            "human_verdict": "pass",
            "label_by": "x",
            "labelled_at": "2026-10-20T08:00:00Z",
        }
    ]
    r2 = on.client.post(
        "/console/factory/mr-agent/golden",
        data={"version": "0.1", "kind": "labels"},
        files={
            "file": ("labels.json", json.dumps({"labels": labels}).encode(), "application/json")
        },
        headers={"X-Dev-User": "reviewer.an", **HX},
    )
    assert r2.status_code == 200 and "21 case(s) stored, 1 refused" in r2.text
    assert len(golden.load_labels(shim.data_dir, "mr-agent")) == 21
    frag = on.get("/console/factory/mr-agent/step/gate", headers=HX).text
    assert "50 of 50 cases" in frag and "21 of 20 calibration labels" in frag
    # the old flat case format still works
    legacy = json.dumps(
        [
            {
                "case_id": "L1",
                "checklist_id": "MR-01",
                "input": "He thong co chu so huu.",
                "expected_verdict": "pass",
            }
        ]
    ).encode()
    r3 = on.client.post(
        "/console/factory/mr-agent/golden",
        data={"version": "0.1"},
        files={"file": ("old.json", legacy, "application/json")},
        headers={"X-Dev-User": "reviewer.an", **HX},
    )
    assert "1 case(s) stored, 0 refused" in r3.text


# ------------------------------------------------------------------------------ runs


def test_sample_run_from_the_console_never_promotes(on: Console) -> None:
    create(on)
    seed(on)
    r = start(on, "sample", n="5")
    assert r.status_code == 200 and "sample run" in r.text and "queued" in r.text
    frag = on.get("/console/factory/mr-agent/step/gate", headers=HX).text
    assert (
        'data-kind="sample"' in frag
        and 'data-status="done"' in frag
        and 'data-verdict="pass"' in frag
    )
    assert row(on)["state"] == "draft"
    assert len(actions(on, "/console/factory/mr-agent/gate/run")) == 2  # attempted + outcome


def test_full_run_tests_the_version_and_the_card_shows_it(on: Console) -> None:
    make_tested(on)
    run = gate.latest_runs(gate.GateEnv.from_console(on.ctx), "mr-agent")[0]
    frag = on.get(f"/console/factory/mr-agent/gate/{run['run_id']}", headers=HX).text
    assert 'data-l1-percent="100"' in frag and 'data-kappa="100"' in frag
    assert (
        'data-table="confusion"' in frag
        and 'data-regression="1"' in frag
        and 'data-layer3="1"' in frag
    )
    assert 'data-cost="1"' in frag and re.search(r"sha256 [0-9a-f]{16}", frag)
    for cid in (
        "schema_valid",
        "evidence_exists",
        "tools_in_scope",
        "no_personal_data",
        "token_budget",
        "stop_points_fire",
        "loop_stops_at_cap",
    ):
        assert f'data-check="{cid}" data-ok="1"' in frag, cid
    card = on.get("/console/factory").text
    assert (
        'data-last-gate="pass"' in card and 'data-gate-kind="full"' in card and "kappa 100" in card
    )
    j = on.client.get(
        "/v1/factory/agents/mr-agent/gate", headers={"X-Dev-User": "viewer.hoa"}
    ).json()
    assert j["runs"][0]["verdict"] == "pass" and j["runs"][0]["cal"]["kappa_hundredths"] == 100
    one = on.client.get(
        f"/v1/factory/gate/{run['run_id']}", headers={"X-Dev-User": "viewer.hoa"}
    ).json()
    assert one["run_id"] == run["run_id"] and one["layer1"]["percent"] == 100
    assert (
        on.client.get(
            "/v1/factory/gate/gate_ffffffffffffffffffff", headers={"X-Dev-User": "admin.chi"}
        ).status_code
        == 400
    )


def test_a_running_row_polls_and_a_state_change_redirects(on: Console) -> None:
    create(on)
    on.ctx.state.insert(
        "gate_run",
        {
            "run_id": "gate_" + "a" * 20,
            "agent_id": "mr-agent",
            "version": "0.1",
            "kind": "full",
            "status": "running",
            "started_at": on.ctx.clock.now(),
            "layer1_json": {"progress": {"done": 3, "total": 50}},
            "layer2_json": {},
            "layer3_json": {},
            "cost_json": {},
            "verdict": "not_run",
            "definition_sha256": "0" * 64,
            "created_by": "x",
        },
    )
    frag = on.get("/console/factory/mr-agent/step/gate", headers=HX).text
    assert 'hx-trigger="every 2s"' in frag and 'data-progress="3/50"' in frag
    poll = on.get("/console/factory/mr-agent/gate?v=0.1&state=draft", headers=HX)
    assert (
        poll.status_code == 200
        and 'data-running="1"' in poll.text
        and "HX-Redirect" not in poll.headers
    )
    moved = on.get("/console/factory/mr-agent/gate?v=0.1&state=live", headers=HX)
    assert moved.headers["HX-Redirect"].endswith("/console/factory/mr-agent?v=0.1&step=gate")


def test_run_refusals_are_400s_with_a_code(on: Console) -> None:
    create(on)
    assert "golden_not_ready" in start(on, "full").text
    assert start(on, "full").status_code == 400
    assert "no_cases" in start(on, "sample").text
    seed(on)
    assert "bad_kind" in start(on, "other").text
    assert (
        "bad_size" in start(on, "sample", n="99").text
        and "bad_size" in start(on, "sample", n="x").text
    )
    assert "bad_systems" in start(on, "simulation").text
    on.ctx.gate_chat = None  # type: ignore[attr-defined]
    on.ctx.settings.llm_base_url = ""
    r = start(on, "sample")
    assert r.status_code == 400 and "model_not_configured" in r.text
    assert on.ctx.state.query("gate_run") == []


def test_a_run_needs_the_group_and_the_role(on: Console) -> None:
    create(on)
    seed(on)
    assert start(on, "sample", "viewer.hoa").status_code == 403  # factory.edit
    assert start(on, "sample", "lead.cyber").status_code == 403  # approver is not factory.edit
    # a user with `groups:` belongs to exactly those groups, whatever the role mapping says
    users = on.ctx.provider.users
    users["rev.cyber"] = AuthPrincipal(
        "rev.cyber", "user", "dev_header", frozenset({"reviewer"}), "x", frozenset({"cyber"})
    )
    users["rev.model"] = AuthPrincipal(
        "rev.model", "user", "dev_header", frozenset({"reviewer"}), "x", frozenset({"model_risk"})
    )
    assert start(on, "sample", "rev.cyber", n="2").status_code == 403
    assert start(on, "sample", "rev.model", n="2").status_code == 200


def test_a_run_is_htmx_only(on: Console) -> None:
    create(on)
    r = on.post(
        "/console/factory/mr-agent/gate/run", {"version": "0.1", "kind": "sample"}, htmx=False
    )
    assert r.status_code == 400


# ------------------------------------------------------------------------------ promotion routes


def test_submit_approve_activate_with_the_roles_of_the_users_file(on: Console) -> None:
    make_tested(on)
    frag = on.get("/console/factory/mr-agent/step/gate", headers=HX).text
    assert 'data-act="submit"' in frag
    # an approval before the submit is refused
    assert "not_submitted" in promote(on, "approve", "lead.model", kind="owner_lead").text
    ok = promote(on, "submit", "reviewer.an")
    assert ok.status_code == 200 and ok.headers["HX-Redirect"].endswith("step=gate")
    assert (
        promote(on, "approve", "reviewer.an", kind="owner_lead").status_code == 403
    )  # no factory.approve
    a1 = promote(on, "approve", "lead.model", kind="owner_lead", note="Checked the evidence.")
    assert a1.status_code == 200 and row(on)["state"] == "tested"  # high tier: one is not enough
    assert "not_eligible" in promote(on, "approve", "lead.cyber", kind="second_line").text
    a2 = promote(on, "approve", "second.line", kind="second_line")
    assert a2.status_code == 200 and row(on)["state"] == "approved"
    wrong = promote(on, "activate", "lead.cyber")  # an approver of another group
    assert wrong.status_code == 400 and "not_eligible" in wrong.text
    live = promote(on, "activate", "lead.model")
    assert live.status_code == 200 and row(on)["state"] == "live"
    approvals = row(on)["definition"]["lifecycle"]["approvals"]
    assert [a["role"] for a in approvals] == ["owner_lead", "second_line"] and approvals[0][
        "by"
    ] == "lead.model"
    card = on.get("/console/factory").text
    assert 'data-live-version="0.1"' in card and 'data-kind="live_agent"' in card
    editor = on.get("/console/factory/mr-agent?step=gate").text
    for ev in ("tested", "submitted", "approval", "approved", "live"):
        assert f'data-event="{ev}"' in editor, ev
    for action in ("submit", "approve", "activate"):
        assert len(actions(on, f"/console/factory/mr-agent/promote/{action}")) >= 2


def test_same_person_and_author_rules_are_400(on: Console) -> None:
    make_tested(on)
    promote(on, "submit", "reviewer.an")
    one = promote(on, "approve", "admin.chi", kind="owner_lead")
    assert one.status_code == 200
    two = promote(on, "approve", "admin.chi", kind="second_line")
    assert two.status_code == 400 and "same_person" in two.text and row(on)["state"] == "tested"
    # the author with an approver role is refused
    assert create(on, "bn-agent", "reviewer.binh").status_code == 200
    seed(on, "bn-agent")
    assert start(on, "full", "reviewer.binh", "bn-agent").status_code == 200
    promote(on, "submit", "reviewer.binh", "bn-agent")
    r = promote(on, "approve", "reviewer.binh", "bn-agent", kind="owner_lead")
    assert r.status_code == 400 and "author_cannot_approve" in r.text


def test_reject_reopen_and_the_reason_lengths(on: Console) -> None:
    make_tested(on)
    promote(on, "submit", "reviewer.an")
    short = promote(on, "reject", "lead.model", reason="too short")
    assert short.status_code == 400 and "reason_too_short" in short.text
    assert promote(on, "reject", "reviewer.an", reason="x" * 30).status_code == 403
    ok = promote(on, "reject", "lead.model", reason="The checklist does not cover drift.")
    assert ok.status_code == 200 and row(on)["state"] == "draft"
    assert row(on)["definition"]["lifecycle"]["approvals"] == []
    # reopen: back to draft by the author with a reason
    promote(on, "submit", "reviewer.an")  # a draft cannot be submitted
    assert row(on)["state"] == "draft"
    shim_run = start(on, "full")
    assert shim_run.status_code == 200 and row(on)["state"] == "tested"
    assert "reason_needed" in promote(on, "reopen", "reviewer.an", reason="no").text
    assert (
        promote(on, "reopen", "reviewer.an", reason="Need to change the checklist.").status_code
        == 200
    )
    assert row(on)["state"] == "draft"


def test_rollback_is_admin_only(on: Console) -> None:
    make_tested(on)
    promote(on, "submit", "reviewer.an")
    promote(on, "approve", "lead.model", kind="owner_lead")
    promote(on, "approve", "second.line", kind="second_line")
    promote(on, "activate", "lead.model")
    on.post("/console/factory/mr-agent/new-version", {"version": "0.1"}, "reviewer.an")
    new = row(on, version="0.2")
    d = new["definition"]
    d["instructions"] += " MR-01 MR-02 MR-03 MR-04 MR-05 MR-06 reworded."
    on.ctx.state.update(
        "factory_agent",
        {"id": "mr-agent", "version": "0.2"},
        {"definition_json": d},
        new["row_version"],
    )
    run = on.post(
        "/console/factory/mr-agent/gate/run", {"version": "0.2", "kind": "full"}, "reviewer.an"
    )
    gate.join("mr-agent")
    assert run.status_code == 200 and row(on, version="0.2")["state"] == "tested"
    c2 = {"version": "0.2"}
    on.post("/console/factory/mr-agent/promote/submit", c2, "reviewer.an")
    on.post("/console/factory/mr-agent/promote/approve", {**c2, "kind": "owner_lead"}, "lead.model")
    assert row(on, version="0.2")["state"] == "approved"
    assert (
        on.post("/console/factory/mr-agent/promote/activate", c2, "lead.model").status_code == 200
    )
    assert (
        row(on, version="0.1")["state"] == "retired" and row(on, version="0.2")["state"] == "live"
    )
    panel = on.get("/console/factory/mr-agent/step/gate?v=0.2", "admin.chi", headers=HX).text
    assert 'data-act="rollback"' in panel
    assert (
        'data-act="rollback"'
        not in on.get("/console/factory/mr-agent/step/gate?v=0.2", "lead.model", headers=HX).text
    )
    assert (
        promote(on, "rollback", "lead.model", reason="The new version misses cases.").status_code
        == 403
    )
    assert (
        promote(on, "rollback", "reviewer.an", reason="The new version misses cases.").status_code
        == 403
    )
    short = promote(on, "rollback", "admin.chi", reason="short")
    assert short.status_code == 400 and "reason_needed" in short.text
    done = promote(on, "rollback", "admin.chi", reason="The new version misses drift cases.")
    assert done.status_code == 200
    assert (
        row(on, version="0.1")["state"] == "live" and row(on, version="0.2")["state"] == "retired"
    )
    assert len(actions(on, "/console/factory/mr-agent/promote/rollback")) >= 4  # 2 rows per attempt


def test_a_changed_definition_is_caught_at_approval(on: Console) -> None:
    make_tested(on)
    promote(on, "submit", "reviewer.an")
    r = row(on)
    d = r["definition"]
    d["guardians"] = d["guardians"] + ["extra_guard"]
    on.ctx.state.update(
        "factory_agent",
        {"id": "mr-agent", "version": "0.1"},
        {"definition_json": d},
        r["row_version"],
    )
    res = promote(on, "approve", "lead.model", kind="owner_lead")
    assert (
        res.status_code == 400 and "definition_changed" in res.text and row(on)["state"] == "draft"
    )


def test_unreferenced_checklist_items_block_the_gate_and_the_submit_button(on: Console) -> None:
    create(on)
    seed(on)
    r = row(on)
    d = r["definition"]
    d["instructions"] = "Answer from the evidence only."
    on.ctx.state.update(
        "factory_agent",
        {"id": "mr-agent", "version": "0.1"},
        {"definition_json": d},
        r["row_version"],
    )
    res = start(on, "full")
    assert res.status_code == 400 and "lint_not_ready" in res.text and "MR-01" in res.text


# ------------------------------------------------------------------------------ simulation


def fake_inputs(sid: str, dim: str) -> dict[str, Any]:
    return {
        "system_id": sid,
        "system": {"system_id": sid, "owner_user": "chu-he-thong", "name": f"He thong {sid}"},
        "packs": [{"ref": f"pack-{sid}:1", "label": "do ben", "text": "dat o phien ban hien tai"}],
        "now": "2026-10-28T09:00:00Z",
    }


def test_simulation_page_shows_findings_beside_evidence_and_stores_marks(
    on: Console, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(gate, "system_inputs", lambda ctx, sid, dim: fake_inputs(sid, dim))
    create(on)
    r = start(on, "simulation", systems="sys-a, sys-b")
    assert r.status_code == 200
    run = gate.latest_runs(gate.GateEnv.from_console(on.ctx), "mr-agent")[0]
    assert (
        run["kind"] == "simulation" and run["verdict"] == "not_run" and row(on)["state"] == "draft"
    )
    frag = on.get("/console/factory/mr-agent/step/gate", headers=HX).text
    assert f'href="/console/factory/mr-agent/simulation/{run["run_id"]}"' in frag
    url = f"/console/factory/mr-agent/simulation/{run['run_id']}"
    page = on.get(url)
    assert page.status_code == 200 and "<html" in page.text
    assert 'data-system="sys-a"' in page.text and 'data-system="sys-b"' in page.text
    assert (
        'data-finding="f-MR-01"' in page.text
        and "data-evidence-ref=" in page.text
        and 'lang="vi"' in page.text
    )
    assert 'data-unmarked="12"' in page.text and 'data-act="mark"' in page.text
    viewer = on.get(url, "viewer.hoa").text
    assert 'data-finding="f-MR-01"' in viewer and 'data-act="mark"' not in viewer  # read only
    ok = on.post(
        url + "/mark",
        {"system": "sys-a", "finding_id": "f-MR-01", "mark": "agree", "note": "goi 0912345678"},
        "reviewer.binh",
    )
    assert ok.status_code == 200 and 'data-mark="agree"' in ok.text and "0912345678" not in ok.text
    dis = on.post(
        url + "/mark",
        {
            "system": "sys-b",
            "finding_id": "f-MR-01",
            "mark": "disagree",
            "correct_verdict": "pass",
            "note": "ok",
        },
        "reviewer.binh",
    )
    assert 'data-mark="disagree"' in dis.text and 'data-count="disagree" data-n="1"' in dis.text
    labels = golden.load_labels(Path(on.ctx.settings.data_dir), "mr-agent")
    assert {(x["finding_id"], x["human_verdict"], x["source"]) for x in labels} == {
        ("f-MR-01", "pass", "simulation"),
    } and len(labels) == 2
    bad = on.post(
        url + "/mark",
        {"system": "sys-a", "finding_id": "f-MR-01", "mark": "disagree"},
        "reviewer.binh",
    )
    assert bad.status_code == 400 and "verdict_needed" in bad.text
    long = on.post(
        url + "/mark",
        {"system": "sys-a", "finding_id": "f-MR-01", "mark": "agree", "note": "x" * 301},
        "reviewer.binh",
    )
    assert long.status_code == 400 and "note_too_long" in long.text
    assert (
        on.post(
            url + "/mark",
            {"system": "sys-a", "finding_id": "f-MR-01", "mark": "agree"},
            "viewer.hoa",
        ).status_code
        == 403
    )
    assert len(actions(on, url + "/mark")) >= 4
    assert (
        Path(on.ctx.settings.data_dir)
        / "factory"
        / "mr-agent"
        / "gate"
        / run["run_id"]
        / "review_report.json"
    ).is_file()


def test_simulation_page_for_an_unknown_run_is_400(on: Console) -> None:
    create(on)
    r = on.get("/console/factory/mr-agent/simulation/gate_" + "b" * 20)
    assert r.status_code == 400 and "not_found" in r.text
    assert on.get("/console/factory/mr-agent/simulation/not-a-run").status_code == 400


# ------------------------------------------------------------------------------ RBAC


def test_rbac_matrix_of_the_new_routes(on: Console) -> None:
    from supervisor.core import rbac

    assert rbac.allowed(["approver"], "factory.approve") and rbac.allowed(
        ["admin"], "factory.approve"
    )
    assert not rbac.allowed(["reviewer"], "factory.approve") and not rbac.allowed(
        ["owner"], "factory.approve"
    )
    assert rbac.roles_for("factory.rollback") == ("admin",)
    create(on)
    # everyone may read, nobody without the permission may write
    for user in ("viewer.hoa", "auditor.dung", "operator.khanh"):
        assert on.get("/console/factory/mr-agent/step/gate", user, headers=HX).status_code == 200
        for action in ("submit", "approve", "reject", "activate", "reopen", "rollback"):
            assert promote(on, action, user).status_code == 403, (user, action)
    assert promote(on, "rollback", "reviewer.binh").status_code == 403
    assert promote(on, "approve", "reviewer.an").status_code == 403
    for (m, p), perm in rbac.ROUTES.items():
        if p.startswith(("/console/factory", "/v1/factory")):
            assert perm in rbac.PERMISSIONS, (m, p)


def test_i18n_has_every_key_in_both_languages() -> None:
    from supervisor.console.i18n_factory_gate import FG

    assert all(len(v) == 2 and all(v) for v in FG.values())
    html = Path(__file__).parents[2] / "src" / "supervisor" / "console" / "templates"
    used = set()
    for name in (
        "_factory_step_gate.html",
        "_factory_gate_run.html",
        "_factory_sim_body.html",
        "factory_simulation.html",
    ):
        used |= set(re.findall(r"t\('((?:fg|fa)_[a-z0-9_]+)'", (html / name).read_text()))
    from supervisor.console import i18n_factory

    known = set(FG) | set(i18n_factory.FA)
    assert used <= known, sorted(used - known)
    assert caps.GATE_KINDS == ("full", "sample", "simulation", "shadow") and probe.TESTS


def test_retiring_a_live_version_is_a_release_act(on: Console) -> None:
    make_tested(on)
    promote(on, "submit", "reviewer.an")
    promote(on, "approve", "lead.model", kind="owner_lead")
    promote(on, "approve", "second.line", kind="second_line")
    promote(on, "activate", "lead.model")
    assert row(on)["state"] == "live"
    body = {"version": "0.1", "reason": "No longer needed by the team."}
    assert on.post("/console/factory/mr-agent/retire", body, "reviewer.an").status_code == 403
    assert row(on)["state"] == "live"
    assert on.post("/console/factory/mr-agent/retire", body, "admin.chi").status_code == 200
    assert row(on)["state"] == "retired"

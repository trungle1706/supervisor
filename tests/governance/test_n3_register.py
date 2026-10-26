"""WP-N3: the register workflow v2 at /console/register, end to end on SQLite.

Three prefills (scan node, policy-only agent, blank), validation (HTTP 400 with the field name),
save and resume, the writes of the submit, the off path, EN and VI."""

from __future__ import annotations

import re
from typing import Any

import pytest

from supervisor.governance.register_v2 import service as rs
from supervisor.inventory.graph import Graph
from supervisor.inventory.model import Node
from supervisor.inventory.store import InventoryStore

from .conftest import Console

HX = {"HX-Request": "true"}
ME = "reviewer.an"
NODE_NAME = "app:synthetic-helper"


@pytest.fixture
def reg(on: Console, monkeypatch: pytest.MonkeyPatch) -> Console:
    for flag in ("console_register_v2", "console_nav_v3", "agents_api_enabled"):
        monkeypatch.setattr(on.ctx.settings, flag, True)
    return on


def seed_node(c: Console) -> str:
    g = Graph()
    app = Node(
        "system",
        NODE_NAME,
        status="unmanaged",
        attrs={"role": "databricks_app", "workspace_kind": "app"},
    )
    app.add_evidence("workspace_scan", "workspace:app/synthetic-helper")
    g.add_node(app)
    tbl = Node("dataset", "main.synthetic.accounts", attrs={"workspace_kind": "uc_table"})
    tool = Node("tool", "transfer_money", attrs={"risk_class": "money"})
    g.add_node(tbl)
    g.add_node(tool)
    g.link(g.nodes[app.node_id], "reads", g.nodes[tbl.node_id], "workspace_scan", "ref")
    g.link(g.nodes[app.node_id], "uses", g.nodes[tool.node_id], "workspace_scan", "ref")
    InventoryStore(c.ctx.state, c.ctx.clock).apply(g, source="workspace_scan")
    return app.node_id


def _bare(html: str) -> str:
    """The page without attribute values (data-gap keys are not labels)."""
    return re.sub(r'data-[\w-]+="[^"]*"', "", html)


def new(c: Console, query: str = "", user: str = ME) -> str:
    r = c.get("/console/register/new" + query, user=user, follow_redirects=False)
    assert r.status_code in (302, 303, 307), r.text[:300]
    m = re.search(r"/console/register/(rd_[0-9a-f]{20})/step/1", r.headers["location"])
    assert m, r.headers["location"]
    return m.group(1)


def step(
    c: Console, did: str, n: int, form: dict[str, Any] | None = None, save: bool = False
) -> Any:
    q = "?save=1" if save else ""
    return c.post(f"/console/register/{did}/step/{n}{q}", form or {}, user=ME)


S1 = {
    "name": "N3 helper",
    "kind": "app",
    "owner_user": ME,
    "owner_team": "payments-team",
    "description": "Synthetic helper app.",
}
S2 = {
    "purpose": "Answers staff questions about domestic transfers.",
    "system_type": "assistant",
    "org_role": "deployer",
    "user_segment": "internal",
    "personal_data": "pseudonymised",
    "human_control": "post_review",
}


def fill_all(c: Console, did: str, s1: dict[str, Any] | None = None) -> None:
    assert step(c, did, 1, {**S1, **(s1 or {})}).status_code == 200
    assert step(c, did, 2, S2).status_code == 200
    assert step(c, did, 3).status_code == 200
    assert step(c, did, 4).status_code == 200
    assert step(c, did, 5, {"bind_form": "1"}).status_code == 200


def submit(c: Console, did: str) -> Any:
    return c.post(f"/console/register/{did}/submit", {}, user=ME)


def rows(c: Console, table: str, **where: Any) -> list[dict[str, Any]]:
    return [dict(r) for r in c.ctx.state.query(table, where or None)]


# ------------------------------------------------------------------ off path


def test_off_routes_answer_400_with_the_flag(on: Console) -> None:
    assert on.ctx.settings.console_register_v2 is False
    for url in ("/console/register", "/console/register/new", "/console/register/rd_x/step/1"):
        r = on.get(url)
        assert r.status_code == 400 and "CONSOLE_REGISTER_V2" in r.text, url
    assert on.post("/console/register/rd_x/submit", {}).status_code == 400
    assert rows(on, "registration_draft") == []


def test_off_buttons_absent_and_old_wizard_unchanged(
    on: Console, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(on.ctx.settings, "console_nav_v3", True)
    html = on.get("/console/systems?lang=en").text
    assert "/console/register/new" not in html and "/console/systems/new" in html
    assert on.get("/console/systems/new?lang=en").status_code == 200


def test_on_buttons_present(reg: Console) -> None:
    assert "/console/register/new" in reg.get("/console/systems?lang=en").text
    assert "/console/register/new" in reg.get("/console/?lang=en").text
    assert "/console/register/new" not in reg.get("/console/systems", user="viewer.hoa").text


def test_viewer_cannot_use_it(reg: Console) -> None:
    assert reg.get("/console/register/new", user="viewer.hoa").status_code == 403


# ------------------------------------------------------------------ scan prefill


def test_scan_prefill_to_submit(reg: Console) -> None:
    nid = seed_node(reg)
    did = new(reg, f"?from={nid}")
    d = rs.store_of(reg.ctx).get(did, ME)
    assert d["source_kind"] == "scan" and d["source_ref"] == nid
    sg = d["data"]["sg"]
    assert sg["money_movement"]["value"] is True and sg["money_movement"]["source"] == "scan"
    assert sg["personal_data"]["value"] == "identifiable"
    assert sg["autonomy_level"]["value"] == "l3_tool_using_supervised"
    assert sg["money_movement"]["reason_key"] == "rg2_why_money_tool"
    # step 1 is prefilled, step 2 waits for a click
    html = reg.get(f"/console/register/{did}/step/1?lang=en").text
    assert 'value="synthetic-helper"' in html or "synthetic-helper" in html
    assert "Prefilled from the workspace scan" in html
    html2 = reg.get(f"/console/register/{did}/step/2?lang=en").text
    assert 'data-suggest="money_movement"' in html2 and "a money tool is linked" in html2
    # leaving step 2 empty is a 400 naming the field
    assert step(reg, did, 1, S1).status_code == 200
    r = step(reg, did, 2, {})
    assert r.status_code == 400 and "purpose: is required" in r.text
    # one click accepts a suggestion; then the person changes another one
    r = step(reg, did, 2, {"purpose": S2["purpose"], "accept": "money_movement"})
    assert r.status_code == 200
    d = rs.store_of(reg.ctx).get(did, ME)
    assert d["data"]["v"]["money_movement"] is True and d["step"] == 2
    html2 = reg.get(f"/console/register/{did}/step/2?lang=en").text
    assert 'data-mark="scan"' not in html2 or 'data-mark="person"' in html2
    r = step(reg, did, 2, {**S2, "accept": "*"})
    assert r.status_code == 200
    d = rs.store_of(reg.ctx).get(did, ME)
    assert d["data"]["v"]["personal_data"] == "identifiable"
    assert (
        step(reg, did, 2, {**S2, "money_movement": "1", "personal_data": "none"}).status_code == 200
    )
    assert rs.mark(rs.store_of(reg.ctx).get(did, ME), "personal_data") == "person"
    assert step(reg, did, 3).status_code == 200
    # step 4: proposal and questions render; the person answers one
    html4 = reg.get(f"/console/register/{did}/step/4?lang=en").text
    assert 'data-register="proposal"' in html4 and 'data-table="questions"' in html4
    assert step(reg, did, 4).status_code == 200
    assert step(reg, did, 5, {"bind_form": "1"}).status_code == 200
    review = reg.get(f"/console/register/{did}/step/6?lang=en").text
    assert 'data-register="review"' in review and "SYS-INTAKE-CONFIRM" in review
    before = len(rows(reg, "guardian_binding"))
    r = submit(reg, did)
    assert r.status_code == 200 and "HX-Redirect" in r.headers
    # the writes
    sys_rows = rows(reg, "ai_system", name="N3 helper")
    assert len(sys_rows) == 1
    sid = sys_rows[0]["system_id"]
    assert sys_rows[0]["status"] == "draft" and sys_rows[0]["lifecycle_stage"] == "initiation"
    assert sys_rows[0]["decision33_class"] == "unclassified"
    team = rows(reg, "system_team", system_id=sid)
    assert [(t["user_id"], t["team_role"]) for t in team] == [(ME, "system_owner")]
    comps = rows(reg, "system_component", system_id=sid)
    assert [(c["ref_kind"], c["ref_id"]) for c in comps] == [("node", nid)]
    cls = rows(reg, "classification", system_id=sid)
    assert len(cls) == 1 and cls[0]["status"] == "draft"
    assert len(rows(reg, "guardian_binding")) == before  # nothing set off: no row
    tasks = {t["template_id"] for t in rows(reg, "task", agent_id=sid)}
    assert {"SYS-INTAKE-CONFIRM", "SYS-INTAKE-CHECKS"} <= tasks
    assert rows(reg, "agent", agent_id="") == []
    # the draft is submitted and the result page lists the next actions
    d = rs.store_of(reg.ctx).get(did, ME)
    assert d["status"] == "submitted"
    page = reg.get(f"/console/register/{did}/result?lang=en").text
    assert 'data-register="done"' in page and sid in page
    # a repeat submit and a step edit are refused with 400
    assert submit(reg, did).status_code == 400
    assert step(reg, did, 1, S1).status_code == 400
    # the audit rows of the submit
    acts = [a for a in rows(reg, "console_action") if a["path"].endswith("/submit")]
    assert [a["outcome"] for a in acts] == ["attempted", "ok", "attempted", "error"]  # 2nd = repeat
    # nothing about the draft reached the chain
    assert not [e for e in rows(reg, "chain_entry") if "registration_draft" in str(e)]


def test_scan_candidate_checks(reg: Console) -> None:
    assert reg.get("/console/register/new?from=nope", follow_redirects=False).status_code == 400
    assert reg.get("/console/register/new?from=a b", follow_redirects=False).status_code == 400
    nid = seed_node(reg)
    assert (
        reg.get(f"/console/register/new?from={nid}&agent=x", follow_redirects=False).status_code
        == 400
    )


# ------------------------------------------------------------------ policy-only agent


POLICY_ONLY = "n3-policy-only"


@pytest.fixture
def policy_only(reg: Console, monkeypatch: pytest.MonkeyPatch) -> str:
    """The deployed policy gets one more agent that has no registry row."""
    from types import SimpleNamespace

    from supervisor.gateway.policy import AgentManifest

    pol = reg.ctx.runtime.gateway.states.policy
    cur = pol.current()
    extra = AgentManifest(
        name="N3 policy-only agent",
        owner_user="payops-lead@example.invalid",
        owner_team="payments-team",
        risk_tier="high",
        model_family="qwen",
        host_type="python",
        plug_point="sdk",
        initial_state="SHADOW",
    )
    doc = cur.doc.model_copy(update={"agents": {**cur.doc.agents, POLICY_ONLY: extra}})
    monkeypatch.setattr(pol, "current", lambda: SimpleNamespace(doc=doc))
    assert reg.ctx.state.get("agent", {"agent_id": POLICY_ONLY}) is None
    return POLICY_ONLY


def policy_only_agent(c: Console) -> str:
    return POLICY_ONLY


def test_policy_agent_prefill_creates_row_and_link(reg: Console, policy_only: str) -> None:
    aid = policy_only_agent(reg)
    manifest = rs.policy_agents(reg.ctx)[aid]
    did = new(reg, f"?agent={aid}")
    d = rs.store_of(reg.ctx).get(did, ME)
    assert d["source_kind"] == "policy"
    assert d["data"]["v"]["owner_team"] == manifest.owner_team
    assert d["data"]["sg"]["model_family"]["source"] == "policy"
    page = reg.get(f"/console/register/{did}/step/3?lang=en").text
    assert 'data-gap="rg2_chk_policy"' in page and 'data-status="ok"' in page
    fill_all(reg, did, {"name": "N3 policy agent", "owner_team": manifest.owner_team})
    assert submit(reg, did).status_code == 200
    ag = rows(reg, "agent", agent_id=aid)
    assert len(ag) == 1 and ag[0]["gate_state"] in ("SHADOW", "RUNNING")
    sid = rows(reg, "ai_system", name="N3 policy agent")[0]["system_id"]
    comps = rows(reg, "system_component", system_id=sid)
    assert [(c["ref_kind"], c["ref_id"]) for c in comps] == [("agent", aid)]
    assert not [t for t in rows(reg, "task", agent_id=sid) if t["template_id"] == "SYS-REG-POLICY"]


def test_policy_agent_unknown_or_registered_is_400(reg: Console) -> None:
    r = reg.get("/console/register/new?agent=ghost-agent", follow_redirects=False)
    assert r.status_code == 400 and "agent" in r.text
    registered = next(
        a["agent_id"] for a in rows(reg, "agent") if a["agent_id"] in rs.policy_agents(reg.ctx)
    )
    assert (
        reg.get(f"/console/register/new?agent={registered}", follow_redirects=False).status_code
        == 400
    )


# ------------------------------------------------------------------ blank, tasks, validation


def test_blank_with_agent_id_unknown_to_policy_opens_the_task(reg: Console) -> None:
    did = new(reg)
    d = rs.store_of(reg.ctx).get(did, ME)
    assert d["source_kind"] == "blank" and d["data"]["sg"] == {}
    page = reg.get(f"/console/register/{did}/step/1?lang=en").text
    assert "Prefilled" not in page
    fill_all(reg, did, {"agent_id": "ghost-agent"})
    n_agents = len(rows(reg, "agent"))
    assert submit(reg, did).status_code == 200
    assert len(rows(reg, "agent")) == n_agents  # the policy does not know it: no row
    sid = rows(reg, "ai_system", name="N3 helper")[0]["system_id"]
    assert rows(reg, "system_component", system_id=sid) == []
    ids = {t["template_id"] for t in rows(reg, "task", agent_id=sid)}
    assert {"SYS-REG-POLICY", "SYS-REG-SPID"} <= ids


def test_agents_api_off_opens_the_task_instead(
    reg: Console, policy_only: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(reg.ctx.settings, "agents_api_enabled", False)
    aid = policy_only_agent(reg)
    did = new(reg, f"?agent={aid}")
    review = rs.agent_plan(reg.ctx, aid, rs.store_of(reg.ctx).get(did, ME))
    assert review["create_row"] is False and review["task_policy"] and review["needs_flag"]
    fill_all(reg, did, {"name": "N3 api off", "owner_team": "payments-team"})
    assert submit(reg, did).status_code == 200
    assert rows(reg, "agent", agent_id=aid) == []


@pytest.mark.parametrize(
    ("n", "form", "field"),
    [
        (1, {**S1, "kind": "spaceship"}, "kind"),
        (1, {**S1, "agent_id": "bad id!"}, "agent_id"),
        (1, {**S1, "name": ""}, "name"),
        (1, {**S1, "owner_team": ""}, "owner_team"),
        (2, {**S2, "system_type": "robot"}, "system_type"),
        (2, {**S2, "personal_data": "everything"}, "personal_data"),
        (2, {**S2, "model_family": "bad family"}, "model_family"),
        (2, {**S2, "autonomy_level": "l9"}, "autonomy_level"),
        (4, {"a_Q-PRE-APPROVAL": "maybe"}, "a_Q-PRE-APPROVAL"),
    ],
)
def test_bad_value_is_400_with_the_field(
    reg: Console, n: int, form: dict[str, Any], field: str
) -> None:
    did = new(reg)
    if n > 1:
        assert step(reg, did, 1, S1).status_code == 200
    r = step(reg, did, n, form)
    assert r.status_code == 400 and f"{field}:" in r.text
    assert 'data-register="error"' in r.text  # the step page itself, with the message


def test_bad_ids_and_other_users_draft_are_400(reg: Console) -> None:
    did = new(reg)
    assert reg.get(f"/console/register/{did}/step/9").status_code == 400
    assert reg.get(f"/console/register/{did}/step/x").status_code == 400
    assert reg.get("/console/register/nope/step/1").status_code == 400
    assert reg.get(f"/console/register/{did}/step/1", user="admin.minh").status_code == 400
    assert reg.post(f"/console/register/{did}/submit", {}, user="admin.minh").status_code == 400
    # submit with the required fields empty: 400, nothing written
    assert submit(reg, did).status_code == 400
    assert rows(reg, "ai_system") == []


def test_duplicate_name_is_400_at_step_1(reg: Console) -> None:
    did = new(reg)
    assert step(reg, did, 1, S1).status_code == 200
    fill_all(reg, did)
    assert submit(reg, did).status_code == 200
    did2 = new(reg)
    r = step(reg, did2, 1, S1)
    assert r.status_code == 400 and "name:" in r.text


# ------------------------------------------------------------------ save and resume


def test_save_for_later_and_resume(reg: Console) -> None:
    did = new(reg)
    r = step(reg, did, 1, {"name": "Half done", "kind": "job"}, save=True)
    assert r.status_code == 200 and r.headers["HX-Redirect"] == "/console/register?saved=1"
    lst = reg.get("/console/register?lang=en").text
    assert did in lst and "Half done" in lst and "Resume" in lst
    page = reg.get(f"/console/register/{did}/step/1?lang=en").text
    assert 'value="Half done"' in page
    # going forward needs the required fields
    assert step(reg, did, 1, {"name": "Half done", "kind": "job"}).status_code == 400
    # plain form post (no HTMX header): 303 to the next step
    r = reg.client.post(
        f"/console/register/{did}/step/1",
        data=S1,
        headers={"X-Dev-User": ME, "Sec-Fetch-Site": "same-origin"},
        follow_redirects=False,
    )
    assert r.status_code == 303 and r.headers["location"].endswith(f"/{did}/step/2")
    assert rs.store_of(reg.ctx).get(did, ME)["step"] == 2
    # drop it
    assert reg.post(f"/console/register/{did}/abandon", {}).status_code == 200
    assert did not in reg.get("/console/register?lang=en").text


# ------------------------------------------------------------------ guardians


def test_guardian_set_off_writes_a_row_and_floor_is_locked(
    reg: Console, monkeypatch: pytest.MonkeyPatch
) -> None:
    for flag in ("guardian_bindings_enabled", "detectors_enabled"):
        monkeypatch.setattr(reg.ctx.settings, flag, True)
    did = new(reg)
    assert step(reg, did, 1, S1).status_code == 200
    assert (
        step(reg, did, 2, {**S2, "autonomy_level": "l3_tool_using_supervised"}).status_code == 200
    )
    view = rs.guardian_view(reg.ctx, reg.ctx and _me(), rs.store_of(reg.ctx).get(did, ME))
    locked = [r for r in view["rows"] if r["locked"]]
    free = [r for r in view["rows"] if r["bindable"]]
    assert locked and free
    html = reg.get(f"/console/register/{did}/step/5?lang=en").text
    assert f'name="on_{free[0]["slug"]}"' in html and f'name="on_{locked[0]["slug"]}"' not in html
    form = {"bind_form": "1", **{f"on_{r['slug']}": "1" for r in free[1:]}}
    assert step(reg, did, 5, form).status_code == 200
    assert rs.store_of(reg.ctx).get(did, ME)["data"]["off"] == [free[0]["slug"]]
    assert step(reg, did, 3).status_code == 200
    assert step(reg, did, 4).status_code == 200
    assert submit(reg, did).status_code == 200
    sid = rows(reg, "ai_system", name="N3 helper")[0]["system_id"]
    b = rows(reg, "guardian_binding", system_id=sid)
    assert [(x["feature_slug"], x["state"]) for x in b] == [(free[0]["slug"], "off")]


def _me() -> Any:
    from tests.governance.conftest import person

    return person(ME, "reviewer")


# ------------------------------------------------------------------ step 4 answers, VI


def test_step4_answers_reach_the_classification_draft(reg: Console) -> None:
    did = new(reg)
    assert step(reg, did, 1, S1).status_code == 200
    assert step(reg, did, 2, S2).status_code == 200
    flow = reg.ctx.classification.flow()
    qid = next(q.id for q in flow.questions if q.derive is None)
    r = step(reg, did, 4, {f"a_{qid}": "yes", f"j_{qid}": "checked with the owner"})
    assert r.status_code == 200
    assert step(reg, did, 5, {"bind_form": "1"}).status_code == 200
    assert submit(reg, did).status_code == 200
    sid = rows(reg, "ai_system", name="N3 helper")[0]["system_id"]
    draft = reg.ctx.classification.get(sid)["draft"]
    ans = next(a for a in draft["answers"] if a["id"] == qid)
    assert ans["answer"] == "yes" and ans["source"] == "person"
    assert reg.ctx.classification.get(sid)["applied"] is None


@pytest.mark.parametrize("lang", ["en", "vi"])
def test_all_steps_render_in_both_languages(reg: Console, lang: str) -> None:
    did = new(reg)
    fill_all(reg, did)
    for n in range(1, 7):
        r = reg.get(f"/console/register/{did}/step/{n}?lang={lang}")
        assert r.status_code == 200, (n, r.text[:200])
        assert "rg2_" not in _bare(r.text), (n, re.findall(r"rg2_\w+", _bare(r.text))[:3])
    assert ("Đăng ký hệ thống AI" in r.text) == (lang == "vi")
    assert reg.get(f"/console/register?lang={lang}").status_code == 200
    assert submit(reg, did).status_code == 200
    page = reg.get(f"/console/register/{did}/result?lang={lang}")
    assert page.status_code == 200 and "rg2_" not in _bare(page.text)


# ------------------------------------------------------------------ review (fuzz, double submit)


def test_fuzz_bad_input_is_never_500(reg: Console) -> None:
    did = new(reg)
    for n in ("0", "7", "abc", "-1", "²", "1.5", "99999999999999999999", "%00"):
        for method in ("get", "post"):
            r = (
                reg.get(f"/console/register/{did}/step/{n}")
                if method == "get"
                else reg.post(f"/console/register/{did}/step/{n}", {}, user=ME)
            )
            assert r.status_code < 500, (n, method, r.status_code)
    for q in (
        "?from=../",
        "?from=%00",
        "?from=" + "a" * 5000,
        "?agent=<script>",
        "?agent=x&from=y",
    ):
        r = reg.get("/console/register/new" + q, follow_redirects=False)
        assert r.status_code in (302, 303, 307, 400), (q, r.status_code)
    for bad in ("rd_" + "0" * 20, "../x", "rd_<script>", "x" * 3000, "rd_%00"):
        for path in ("step/1", "result"):
            assert reg.get(f"/console/register/{bad}/{path}").status_code < 500
        assert reg.post(f"/console/register/{bad}/submit", {}, user=ME).status_code < 500
        assert reg.post(f"/console/register/{bad}/abandon", {}, user=ME).status_code < 500
    long = "x" * 100_000
    forms = [
        {"name": long},
        {"description": long},
        {"kind": "zzz", "name": "a"},
        {"agent_id": "<script>"},
        {"name": "a\x00b"},
        {"accept": "nope"},
        {"accept": "*"},
        {"run": "1", "repo_path": "../../etc"},
    ]
    for n in range(1, 7):
        for f in forms:
            assert reg.post(f"/console/register/{did}/step/{n}", f, user=ME).status_code < 500
    assert step(reg, did, 1, S1).status_code == 200
    for f in (
        {"purpose": long},
        {"system_type": "bad"},
        {"autonomy_level": "bad"},
        {"model_family": "a b c"},
        {"data_sources": long},
    ):
        assert reg.post(f"/console/register/{did}/step/2", f, user=ME).status_code < 500
    for f in ({"a_Q-PRE-APPROVAL": "yes", "j_Q-PRE-APPROVAL": long}, {"a_nope": "yes"}):
        assert reg.post(f"/console/register/{did}/step/4", f, user=ME).status_code < 500
    assert (
        reg.post(f"/console/register/{did}/step/5", {"bind_form": "1"}, user=ME).status_code < 500
    )


def test_submit_twice_writes_once_and_submitted_draft_is_not_editable(reg: Console) -> None:
    did = new(reg)
    fill_all(reg, did)
    assert submit(reg, did).status_code == 200
    n = len(rows(reg, "ai_system"))
    assert submit(reg, did).status_code == 400
    assert step(reg, did, 1, S1).status_code == 400
    assert reg.post(f"/console/register/{did}/abandon", {}, user=ME).status_code == 400
    assert len(rows(reg, "ai_system")) == n == 1
    assert reg.get(f"/console/register/{did}/result").status_code == 200

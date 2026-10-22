"""WP-G6 review fixes: masking of free text (H1), chain_verify as a write (M1), classification
drafts of people (M2), draft fields (M3), KPI bounds, cache and page (M5, M6), read audit (M7),
and the lows."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from supervisor.config import REPO_ROOT
from supervisor.governance import kpis
from supervisor.mcp_server.auth import principal_of

from .conftest import Cred, Rig
from .test_tools_library_supervisor import _draft

PII = "Nguyen Van An an.nguyen@tcb.vn CCCD 012345678901 0912345678"
TOKENS = ("Nguyen Van An", "an.nguyen@tcb.vn", "012345678901", "0912345678")


def put(rig: Rig, table: str, key: dict[str, Any], **changes: Any) -> None:
    row = rig.ctx.state.get(table, key)
    assert row is not None, (table, key)
    rig.ctx.state.update(table, key, changes, row["row_version"])


def blob_of(out: Any) -> str:
    return json.dumps(out, ensure_ascii=False, default=str)


# ------------------------------------------------------------------------ H1


def seed_everything(rig: Rig, cred: Cred) -> tuple[str, str]:
    """Personal data in every free-text field that a tool can return."""
    ctx = rig.ctx
    ctx.settings.governance_actions_enabled = True
    sid = rig.ok(cred, "register_system", {"draft": _draft(), "confirm": True})["system_id"]
    rig.ok(
        cred,
        "link_component",
        {"system_id": sid, "ref_kind": "agent", "ref_id": "payments", "confirm": True},
    )
    put(
        rig,
        "ai_system",
        {"system_id": sid},
        name=f"Sys {PII}",
        purpose=PII,
        risk_justification=PII,
        owner_team=f"Team {PII}",
        tags=json.dumps({"note": PII, "list": [PII]}),
    )
    comp = ctx.state.query("system_component", {"system_id": sid})[0]
    put(rig, "system_component", {"component_id": comp["component_id"]}, evidence_ref=PII)
    risk = ctx.risks.create(
        {
            "title": "t",
            "description": "d",
            "category": "pii",
            "agent_id": "payments",
            "inherent_likelihood": 3,
            "inherent_impact": 3,
            "treatment": "mitigate",
            "owner": "o",
            "status": "draft",
        },
        "reviewer.an",
    )
    put(
        rig,
        "risk",
        {"risk_id": risk["risk_id"]},
        title=PII,
        description=PII,
        treatment_note=PII,
        marginal_note=PII,
        owner=PII,
    )
    from supervisor.console import systems_wizard

    systems_wizard.open_tasks(ctx, sid, "reviewer.an")
    for t in ctx.state.query("task", {"agent_id": sid}):
        put(rig, "task", {"task_id": t["task_id"]}, title=PII)
    ctx.risks.import_path(REPO_ROOT / "config" / "risks", "reviewer.an")
    ctx.controls.import_path(REPO_ROOT / "config" / "controls", "reviewer.an")
    put(rig, "control", {"control_id": "CTL-PII-MASK"}, title=PII, objective=PII, owner=PII)
    ctx.state.insert(
        "review",
        {
            "review_id": "rv_" + "a" * 16,
            "system_id": sid,
            "kind": "internal",
            "title": PII,
            "scope": [],
            "reviewer_user": "reviewer.binh",
            "status": "planned",
            "reports": [{"kind": "note", "ref": PII, "sha256": ""}],
            "locked": False,
            "reopen_reason": PII,
            "reopen_count": 0,
            "created_at": ctx.clock.now(),
            "created_by": "reviewer.an",
        },
    )
    ctx.state.insert(
        "incident",
        {
            "incident_id": "inc_" + "b" * 24,
            "system_id": sid,
            "agent_id": "payments",
            "kind": "alert",
            "severity": "high",
            "title": PII,
            "event_ref": "alert:x",
            "root_cause": PII,
            "affected_scope": PII,
            "status": "open",
            "opened_at": ctx.clock.now(),
        },
    )
    return str(sid), str(risk["risk_id"])


def test_no_tool_returns_personal_data_from_a_free_text_field(rig: Rig) -> None:
    cred = rig.new_app("sweep", roles=("reviewer", "owner"))
    sid, risk_id = seed_everything(rig, cred)
    ctx = rig.ctx
    # an open draft made by a person, with PII in a justification
    rig.ok(cred, "classification_draft", {"system_id": sid, "confirm": True})
    cls = ctx.state.query("classification", {"system_id": sid})[0]
    answers = json.loads(cls["answers"]) if isinstance(cls["answers"], str) else cls["answers"]
    first = next(iter(answers))
    answers[first]["justification"] = PII
    put(
        rig,
        "classification",
        {"classification_id": cls["classification_id"]},
        answers=json.dumps(answers),
        created_by="reviewer.an",
    )
    task_id = ctx.state.query("task", {"agent_id": sid})[0]["task_id"]
    calls: list[tuple[str, dict[str, Any]]] = [
        *[
            ("list_entities", {"kind": k})
            for k in ("system", "risk", "control", "incident", "review")
        ],
        ("get_entity", {"kind": "system", "id": sid}),
        ("get_entity", {"kind": "risk", "id": risk_id}),
        ("get_entity", {"kind": "control", "id": "CTL-PII-MASK"}),
        ("get_entity", {"kind": "incident", "id": "inc_" + "b" * 24}),
        ("get_entity", {"kind": "review", "id": "rv_" + "a" * 16}),
        ("list_tasks", {"system_id": sid}),
        *[
            ("transparency_report", {"system_id": sid, "variant": v})
            for v in ("regulator", "customer", "internal")
        ],
        ("classification_draft", {"system_id": sid}),
        ("classification_draft", {"system_id": sid, "confirm": True}),
        ("complete_task", {"task_id": task_id}),
        (
            "register_system",
            {"draft": {**_draft(), "name": "New one", "purpose": PII, "tags": {"n": PII}}},
        ),
        (
            "propose_risk",
            {
                "system_id": sid,
                "agent_id": "payments",
                "title": PII,
                "description": PII,
                "category": "pii",
                "inherent_likelihood": 3,
                "inherent_impact": 3,
                "treatment": "mitigate",
                "treatment_note": PII,
                "owner": PII,
            },
        ),
        ("kpis", {}),
        ("gate_state", {"agent_id": "payments"}),
        ("decisions", {"agent_id": "payments"}),
    ]
    seen = []
    for name, args in calls:
        out = rig.call(cred, name, args)
        assert "result" in out, (name, args, out)
        seen.append(blob_of(out))
    blob = "\n".join(seen)
    assert len(blob) > 8000
    for token in TOKENS:
        assert token not in blob, f"{token!r} is in a tool result"
    # the masker did run: its tokens are there
    assert "<PERSON:" in blob and "<EMAIL:" in blob and "<PHONE:" in blob


def test_with_no_masker_the_text_fields_come_back_empty(rig: Rig) -> None:
    cred = rig.new_app("sweep", roles=("reviewer", "owner"))
    sid = rig.ok(cred, "register_system", {"draft": _draft(), "confirm": True})["system_id"]
    put(rig, "ai_system", {"system_id": sid}, purpose=PII)
    rig.ctx.settings.masker_kind = "none"
    if hasattr(rig.ctx, "_mcp_masker"):
        del rig.ctx._mcp_masker
    item = rig.ok(cred, "get_entity", {"kind": "system", "id": sid})["item"]
    assert item["purpose"] == "" and item["name"] == ""
    assert item["system_id"] == sid and item["system_type"] == "assistant"  # ids and enums stay


def test_gate_state_drops_the_principal_of_a_resume_approval(rig: Rig) -> None:
    cred = rig.new_app()
    out = rig.ok(cred, "gate_state", {"agent_id": "payments"})
    assert set(out) == {"agent_id", "state", "pending_resume"}
    for p in out["pending_resume"]:
        assert set(p) <= {"role", "ts"}


# ------------------------------------------------------------------------ M2


def test_a_draft_of_a_person_is_never_replaced(rig: Rig) -> None:
    cred = rig.new_app()
    sid = rig.ok(cred, "register_system", {"draft": _draft(), "confirm": True})["system_id"]
    first = rig.ok(cred, "classification_draft", {"system_id": sid, "confirm": True})
    assert first["written"] is True
    # the app may remake its own draft
    again = rig.ok(cred, "classification_draft", {"system_id": sid, "confirm": True})
    assert again["written"] is True
    cls = rig.ctx.state.query("classification", {"system_id": sid})[0]
    # a person edits an answer: the draft is theirs now, even though the app made it
    answers = json.loads(cls["answers"]) if isinstance(cls["answers"], str) else cls["answers"]
    q = next(iter(answers))
    answers[q] = {"answer": True, "source": "person", "justification": "I checked"}
    put(
        rig,
        "classification",
        {"classification_id": cls["classification_id"]},
        answers=json.dumps(answers),
    )
    for args in ({"system_id": sid}, {"system_id": sid, "confirm": True}):
        out = rig.call(cred, "classification_draft", args)["result"]["structuredContent"]
        body = out.get("planned_change", out)
        assert body["refused"] is True and body["written"] is False
        assert body["classification"]["classification_id"] == cls["classification_id"]
    after = rig.ctx.state.get("classification", {"classification_id": cls["classification_id"]})
    stored = json.loads(after["answers"]) if isinstance(after["answers"], str) else after["answers"]
    assert stored[q]["justification"] == "I checked"  # not reset


def test_a_draft_made_by_a_person_is_refused_from_the_start(rig: Rig) -> None:
    cred = rig.new_app()
    sid = rig.ok(cred, "register_system", {"draft": _draft(), "confirm": True})["system_id"]
    rig.ctx.classification.draft(sid, "reviewer.an")
    out = rig.ok(cred, "classification_draft", {"system_id": sid, "confirm": True})
    assert out["refused"] is True and out["written"] is False
    assert (
        rig.ctx.state.query("classification", {"system_id": sid})[0]["created_by"] == "reviewer.an"
    )


# ------------------------------------------------------------------------ M5


def systems_n(rig: Rig, n: int) -> list[str]:
    ids = []
    for i in range(n):
        ids.append(
            rig.ctx.systems.register(
                {**_draft(), "owner_user": "reviewer.an", "name": f"Sys {i}"}, "reviewer.an"
            )["system_id"]
        )
    return [str(i) for i in ids]


def me() -> Any:
    return principal_of({"app_id": "mcp-kpi"}, ["reviewer"])


def test_rule_runs_are_counted_newest_first_and_the_cap_is_reported(
    rig: Rig, monkeypatch: pytest.MonkeyPatch
) -> None:
    systems_n(rig, 3)
    full = kpis.compute(rig.ctx, me(), cache=False)
    assert full["speed"]["automation"]["rule_runs"] >= 3
    assert full["speed"]["automation"]["rule_runs_capped"] is False
    assert "rule_runs" not in full["unavailable"]
    monkeypatch.setattr(kpis, "RUN_CAP", 2)
    capped = kpis.compute(rig.ctx, me(), cache=False)
    assert capped["speed"]["automation"]["rule_runs_capped"] is True
    assert capped["unavailable"]["rule_runs"] == "capped"
    assert capped["speed"]["automation"]["rule_runs"] <= 2


def test_the_state_reads_are_bounded_and_say_so(rig: Rig, monkeypatch: pytest.MonkeyPatch) -> None:
    sids = systems_n(rig, 2)
    now = rig.ctx.clock.now()
    for n in range(2):
        rig.ctx.state.insert(
            "governance_event",
            {
                "event_key": f"k{n}",
                "kind": "alert",
                "severity": "high",
                "agent_id": "payments",
                "system_id": sids[0],
                "ref": "alert:x",
                "event_at": now,
                "status": "done",
                "rules": [],
                "actions": [],
                "started_at": now,
            },
        )
        rig.ctx.state.insert(
            "stage_approval",
            {
                "approval_id": f"sa{n}",
                "system_id": sids[0],
                "from_stage": "initiation",
                "to_stage": "design",
                "requested_by": "reviewer.an",
                "status": "pending",
                "created_at": now,
            },
        )
    ok = kpis.compute(rig.ctx, me(), cache=False)
    assert not [k for k in ok["unavailable"] if k.endswith("_capped")]
    monkeypatch.setattr(kpis, "READ_CAP", 1)
    capped = kpis.compute(rig.ctx, me(), cache=False)
    for table in ("governance_event", "stage_approval", "system_component", "inventory_node"):
        if table in ("system_component", "inventory_node"):
            continue  # fewer rows than the cap in this store
        assert capped["unavailable"][f"{table}_capped"] == "capped"
    assert capped["speed"]["automation"]["events"] == 1  # one row read


def test_an_event_of_no_system_is_nobodys_figure(rig: Rig) -> None:
    """L5."""
    sids = systems_n(rig, 1)
    now = rig.ctx.clock.now()
    for n, system in enumerate((None, "sys_other", sids[0])):
        rig.ctx.state.insert(
            "governance_event",
            {
                "event_key": f"e{n}",
                "kind": "alert",
                "severity": "high",
                "agent_id": "payments",
                "system_id": system,
                "ref": "alert:x",
                "event_at": now,
                "status": "done",
                "rules": [],
                "actions": [],
                "started_at": now,
            },
        )
    assert kpis.compute(rig.ctx, me(), cache=False)["speed"]["automation"]["events"] == 1


def test_compute_is_cached_for_30_seconds_per_scope(
    rig: Rig, monkeypatch: pytest.MonkeyPatch
) -> None:
    now = [100.0]
    monkeypatch.setattr(kpis, "_clock", lambda: now[0])
    systems_n(rig, 1)
    first = kpis.compute(rig.ctx, me())
    systems_n(rig, 0)
    rig.ctx.systems.register(
        {**_draft(), "owner_user": "reviewer.an", "name": "Later one"}, "reviewer.an"
    )
    again = kpis.compute(rig.ctx, me())
    assert first["coverage"]["systems_total"] == again["coverage"]["systems_total"] == 1
    again["coverage"]["systems_total"] = 99  # the caller has a copy
    assert kpis.compute(rig.ctx, me())["coverage"]["systems_total"] == 1
    other = principal_of({"app_id": "mcp-other"}, ["viewer"])  # another scope, another entry
    assert kpis.compute(rig.ctx, other)["coverage"]["systems_total"] == 0
    now[0] += 31
    assert kpis.compute(rig.ctx, me())["coverage"]["systems_total"] == 2
    rig.ctx.systems.register(
        {**_draft(), "owner_user": "reviewer.an", "name": "Third one"}, "reviewer.an"
    )
    assert kpis.compute(rig.ctx, me(), cache=False)["coverage"]["systems_total"] == 3
    kpis.clear_cache()
    assert kpis.compute(rig.ctx, me())["coverage"]["systems_total"] == 3


def test_the_empty_document_has_the_shape_of_a_real_one(rig: Rig) -> None:
    real = kpis.compute(rig.ctx, me(), cache=False)
    empty = kpis.empty("error")

    assert set(empty) == set(real)
    for group in ("coverage", "quality", "speed"):
        assert set(empty[group]) == set(real[group]), group
    assert set(empty["speed"]["automation"]) == set(real["speed"]["automation"])
    assert all(v == "error" for v in empty["unavailable"].values())


# ------------------------------------------------------------------------ M6


def test_the_overview_page_survives_a_failing_kpi_function(
    rig: Rig, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    s = rig.ctx.settings
    s.console_nav_v3 = True
    s.console_systems_enabled = True

    def boom(*a: Any, **k: Any) -> Any:
        raise RuntimeError("store exploded")

    monkeypatch.setattr(kpis, "compute", boom)
    r = rig.console.get("/console/governance?lang=en&scope=all", user="admin.chi")
    assert r.status_code == 200, r.text[:300]
    assert 'data-section="kpis"' in r.text and "could not be computed" in r.text
    assert "store exploded" not in r.text
    assert "the KPIs could not be computed" in caplog.text
    vi = rig.console.get("/console/governance?lang=vi&scope=all", user="admin.chi")
    assert vi.status_code == 200 and "Không tính được số liệu" in vi.text


# ------------------------------------------------------------------------ M7


def test_every_answered_read_leaves_one_ok_row(rig: Rig) -> None:
    cred = rig.new_app()
    sid = rig.ok(cred, "register_system", {"draft": _draft(), "confirm": True})["system_id"]
    before = len(rig.actions())
    rig.ok(cred, "list_entities", {"kind": "system"})
    rig.ok(cred, "get_entity", {"kind": "system", "id": sid})
    rig.ok(cred, "gate_state", {"agent_id": "payments"})
    rig.ok(cred, "regulations")
    rows = rig.actions()[before:]
    assert [r["path"] for r in rows] == [
        "/mcp/tools/list_entities",
        "/mcp/tools/get_entity",
        "/mcp/tools/gate_state",
        "/mcp/tools/regulations",
    ]
    assert {r["outcome"] for r in rows} == {"ok"} and {r["permission"] for r in rows} == {
        "mcp.read"
    }
    assert {r["actor"] for r in rows} == {f"mcp:{cred.app_id}"}
    assert [(r["target_kind"], r["target_id"]) for r in rows] == [
        ("system", None),
        ("system", sid),
        ("agent", "payments"),
        (None, None),
    ]
    # a refused read, a plan and a failed read leave no ok row
    n = len(rig.actions())
    rig.err(cred, "get_entity", {"kind": "system", "id": "sys_none"})
    rig.ok(cred, "register_system", {"draft": {**_draft(), "name": "Plan only"}})
    assert len(rig.actions()) == n


def test_a_store_failure_does_not_stop_a_read(rig: Rig, monkeypatch: pytest.MonkeyPatch) -> None:
    cred = rig.new_app()
    real = rig.ctx.tables.append

    def failing(table: str, rows: Any) -> int:
        if table == "console_action":
            raise OSError("disk full")
        return real(table, rows)

    monkeypatch.setattr(rig.ctx.tables, "append", failing)
    assert rig.ok(cred, "regulations")["count"] > 0


# ------------------------------------------------------------------------ L1, L4


def test_an_app_principal_never_holds_admin() -> None:
    p = principal_of({"app_id": "mcp-x"}, ["admin", "reviewer"])
    assert p.roles == frozenset({"reviewer"}) and p.kind == "service_principal"


def test_the_agent_ingress_refuses_ids_of_the_app_family(tmp_path: Path) -> None:
    from supervisor.config import load_settings
    from supervisor.gateway import ingress_auth
    from supervisor.gateway.ingress_auth import IngressRejected, IngressVerifier
    from supervisor.gateway.ingress_sign import IngressCredential

    settings = load_settings(
        sql_backend="sqlite",
        data_dir=tmp_path / "d",
        llm_base_url="",
        ingress_keys_file=tmp_path / "keys.yaml",
    )
    verifier = ingress_auth.build_verifier(settings)
    assert verifier.refuse_prefixes == ("mcp-",)
    headers = IngressCredential("mcp-nightly", "k" * 64).headers_for("POST", "/gate/check", b"{}")
    with pytest.raises(IngressRejected) as exc:
        verifier.precheck(headers)
    assert exc.value.reason == "unknown_agent"
    ok = IngressCredential("payments", "k" * 64).headers_for("POST", "/gate/check", b"{}")
    assert verifier.precheck(ok) == "hmac"
    # the app verifier itself has no such rule
    assert IngressVerifier(kind="hmac", keys=None).refuse_prefixes == ()


# ------------------------------------------------------------------------ M8 and two people


def test_the_person_who_issued_an_app_cannot_approve_it(rig: Rig) -> None:
    from supervisor.mcp_server.apps import McpAppError

    row = rig.apps.create("self made", ("library.read",), ("viewer",), "admin.chi", "s" * 64)
    with pytest.raises(McpAppError, match="cannot approve"):
        rig.apps.approve(row["app_id"], "admin.chi")
    r = rig.console.client.post(
        f"/v1/mcp/apps/{row['app_id']}/approve", headers={"X-Dev-User": "admin.chi"}
    )
    assert r.status_code == 400 and "cannot approve" in r.json()["error"]
    assert rig.apps.get(row["app_id"])["status"] == "pending"
    rig.apps.approve(row["app_id"], "someone.else")
    assert rig.apps.get(row["app_id"])["status"] == "approved"


def test_masking_leaves_a_clean_report_as_it_is(rig: Rig) -> None:
    """The masker must not change a figure, a date or an id in a report with no personal data."""
    from supervisor.mcp_server.common import plain

    cred = rig.new_app()
    sid = rig.ok(cred, "register_system", {"draft": _draft(), "confirm": True})["system_id"]
    rig.ok(
        cred,
        "link_component",
        {"system_id": sid, "ref_kind": "agent", "ref_id": "payments", "confirm": True},
    )
    for variant in ("regulator", "customer", "internal"):
        out = rig.ok(cred, "transparency_report", {"system_id": sid, "variant": variant})
        data, _info = rig.ctx.transparency.report("payments", variant)
        got = out["agents"][0]["report"]
        want = plain(data)
        for d in (got, want):  # the build time moves between two calls
            d.pop("generated_at", None)
        assert got == want, variant

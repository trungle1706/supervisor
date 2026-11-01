"""WP-F4: the onboarding orchestrator (ONBOARD_ORCHESTRATOR).

Off path first (400 orchestrator_off, no table read, the Risk assessment tab unchanged), then the
plan rules (table-driven), the default rule runner, budgets, the hitl stop, the conflict rule, the
promise that nothing writes ``pass``, the duties pre-fill, run_in_progress, the HTMX panel and RBAC.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import json
import time
from collections.abc import Iterator, Mapping
from pathlib import Path
from typing import Any

import pytest

from supervisor.config import load_settings
from supervisor.factory.schemas.assessment_report_v1 import AssessmentReportV1
from supervisor.governance import risk_dimensions as rd
from supervisor.governance.systems import ALL
from supervisor.onboard import orchestrator as orch

from .conftest import Console, add_agent, draft

CREATOR = "reviewer.an"
VIEWER = "viewer.hoa"
NOW = dt.datetime(2026, 10, 28, 9, 0, tzinfo=dt.UTC)
AGENT = "f4-agent"
TABLE = "orchestrator_run"
FLAGS = ("risk_dimensions", "classification_v2", "onboard_orchestrator")


# ------------------------------------------------------------------ helpers


@pytest.fixture
def orchon(on: Console, monkeypatch: pytest.MonkeyPatch) -> Iterator[Console]:
    from supervisor.app import app
    from supervisor.governance.orchestrator_routes import router as o_router
    from supervisor.governance.risk_dimension_routes import router as rd_router

    from .conftest import restore_app

    for flag in FLAGS:
        monkeypatch.setattr(on.ctx.settings, flag, True)
    saved = list(app.router.routes)
    lifespan = app.router.lifespan_context
    app.include_router(rd_router)
    app.include_router(o_router)
    try:
        yield on
    finally:
        restore_app(app, saved, lifespan)


@pytest.fixture
def orchoff(on: Console) -> Iterator[Console]:
    from supervisor.app import app
    from supervisor.governance.orchestrator_routes import router as o_router
    from supervisor.governance.risk_dimension_routes import router as rd_router

    from .conftest import restore_app

    saved = list(app.router.routes)
    lifespan = app.router.lifespan_context
    app.include_router(rd_router)
    app.include_router(o_router)
    try:
        yield on
    finally:
        restore_app(app, saved, lifespan)


def _system(c: Console, **over: Any) -> str:
    name = over.pop("name", None) or f"System {len(c.ctx.systems.list_systems(ALL, {}))}"
    s = c.ctx.systems.register(draft(owner_user=CREATOR, name=name, **over), CREATOR)
    return str(s["system_id"])


def _classify(c: Console, sid: str, outcome: str, approved: bool = True) -> None:
    tree = c.ctx.classification_v2.tree()
    c.ctx.state.insert(
        "classification_v2",
        {
            "classification_id": f"cls-{sid}-1",
            "system_id": sid,
            "outcome": outcome,
            "path_json": [],
            "tree_sha256": tree.sha256,
            "path_hash": "0" * 64,
            "decided_by": "someone.else",
            "approved_by": "approver.em" if approved else None,
            "approved_at": NOW if approved else None,
            "inherited_from_provider": False,
            "valid_until": NOW + dt.timedelta(days=365),
            "created_at": NOW,
        },
    )


def _ready(c: Console, outcome: str = "high_self", **over: Any) -> str:
    add_agent(c.runtime.adapters, AGENT)
    sid = _system(c, **over)
    c.ctx.systems.link(sid, "agent", AGENT, CREATOR)
    _classify(c, sid, outcome)
    return sid


def _result(c: Console, pack: str, status: str, run: str = "r1") -> None:
    from supervisor.assurance.loader import load_packs

    ver = next(p.version for p in load_packs() if p.id == pack)
    c.ctx.tables.append(
        "eval_result",
        [
            {
                "run_id": run,
                "ts": NOW,
                "pack_id": pack,
                "pack_version": ver,
                "manifest_sha256": "0" * 64,
                "dimension": "security",
                "target_kind": "agent",
                "target_id": AGENT,
                "status": status,
                "metrics": {},
                "metric_status": {},
                "thresholds": {},
                "reasons": "",
                "n_items": 1,
                "data_mode": "synthetic",
                "dataset_id": "d",
                "dataset_sha256": "0" * 64,
                "is_mock": False,
                "launch_gate": "advisory",
                "judge_gate": False,
                "details": {},
                "evidence_hash": None,
            }
        ],
    )


def _all_required(c: Console, status: str = "ok", dims: tuple[str, ...] = rd.DIMENSION_IDS) -> None:
    cfg = rd.load_config()
    seen: set[str] = set()
    for d in cfg.dimensions:
        if d.id not in dims:
            continue
        for m in d.measured_by:
            if m.kind == "pack" and m.required and m.id not in seen:
                seen.add(m.id)
                _result(c, m.id, status, run=f"r-{m.id}")


def _rows(c: Console, sid: str) -> dict[str, dict[str, Any]]:
    return {
        r["dimension_id"]: dict(r)
        for r in c.ctx.state.query("risk_dimension_status", {"system_id": sid})
    }


def _api(c: Console, method: str, url: str, body: Any = None, user: str = CREATOR) -> Any:
    return c.client.request(method, url, json=body, headers={"X-Dev-User": user})


def _items(run: orch.OrchestratorRun) -> dict[str, dict[str, Any]]:
    return {i["dimension_id"]: i for i in run.items}


class Cat:
    def __init__(self, agents: Mapping[str, orch.LiveAgent]) -> None:
        self.agents = agents

    def live_agent(self, dimension_id: str) -> orch.LiveAgent | None:
        return self.agents.get(dimension_id)


def _sys(**over: Any) -> dict[str, Any]:
    base = {
        "system_id": "S1",
        "system_type": "assistant",
        "personal_data": "none",
        "credit_decision": False,
        "user_segment": "internal",
    }
    return {**base, **over}


# ------------------------------------------------------------------ off path


def test_flag_off_by_default_and_needs_the_others(
    console: Console, monkeypatch: pytest.MonkeyPatch
) -> None:
    assert load_settings(llm_base_url="").onboard_orchestrator is False
    s = console.ctx.settings
    monkeypatch.setattr(s, "onboard_orchestrator", True)
    assert orch.enabled(s) is False
    for flag in ("governance_enabled", "risk_dimensions", "classification_v2"):
        monkeypatch.setattr(s, flag, True)
    assert orch.enabled(s) is True
    monkeypatch.setattr(s, "classification_v2", False)
    assert orch.enabled(s) is False


def test_off_routes_400_no_table_read_tab_unchanged(
    orchoff: Console, monkeypatch: pytest.MonkeyPatch
) -> None:
    c = orchoff
    monkeypatch.setattr(c.ctx.settings, "risk_dimensions", True)  # the C2 tab on, F4 off
    sid = _system(c)
    seen: list[str] = []
    real_q, real_g = c.ctx.state.query, c.ctx.state.get

    def spy_q(table: str, *a: Any, **k: Any) -> Any:
        seen.append(table)
        return real_q(table, *a, **k)

    def spy_g(table: str, *a: Any, **k: Any) -> Any:
        seen.append(table)
        return real_g(table, *a, **k)

    monkeypatch.setattr(c.ctx.state, "query", spy_q)
    monkeypatch.setattr(c.ctx.state, "get", spy_g)
    for method, url in (
        ("POST", f"/v1/systems/{sid}/orchestrate"),
        ("GET", f"/v1/systems/{sid}/orchestrate"),
        ("GET", "/v1/orchestrate/orc_x"),
        ("GET", "/v1/orchestrate/orc_x/reports/model"),
    ):
        r = _api(c, method, url, {} if method == "POST" else None)
        assert r.status_code == 400 and "orchestrator_off" in r.text, url
    assert c.get(f"/console/systems/{sid}/orchestrate?lang=en").status_code == 400
    assert c.post(f"/console/systems/{sid}/orchestrate", {}, user=CREATOR).status_code == 400
    tab = c.get(f"/console/systems/{sid}?tab=riskdim&lang=en").text
    assert 'data-act="rd-reassess"' in tab and "disabled" in tab  # the C2 placeholder stays
    assert "orch-panel" not in tab and 'data-act="orch-run"' not in tab
    assert TABLE not in seen


# ------------------------------------------------------------------ the plan


def _applies(p: orch.Plan) -> dict[str, tuple[bool, str]]:
    return {i.dimension_id: (i.applies, i.reason) for i in p.items}


ALL8 = set(rd.DIMENSION_IDS)


@pytest.mark.parametrize(
    ("outcome", "system", "flags", "facts", "institution", "applying", "reasons"),
    [
        ("high_certify", _sys(), {}, None, "bank", ALL8, {"ethics": "high_all_eight"}),
        ("high_self", _sys(), {}, None, "bank", ALL8, {"reputation": "high_all_eight"}),
        (
            "high_self",
            _sys(),
            {},
            None,
            "other",
            ALL8 - {"reputation"},
            {"reputation": "bank_only"},
        ),
        # ethics: n/a without customer decision and personal data, applies with either (medium)
        (
            "medium",
            _sys(user_segment="internal"),
            {},
            {"facts": [{"kind": "file"}]},
            "bank",
            {"model", "data_governance", "cybersecurity", "legal_compliance"},
            {
                "ethics": "no_customer_decision_no_personal_data",
                "third_party": "no_third_party_signal",
                "supply_chain": "no_dependency_signal",
                "reputation": "medium_customer_facing_only",
            },
        ),
        (
            "medium",
            _sys(personal_data="identifiable", user_segment="customer"),
            {},
            {"facts": [{"kind": "model"}, {"kind": "tool"}]},
            "bank",
            ALL8,
            {"third_party": "third_party_signal", "supply_chain": "dependency_signal"},
        ),
        (
            "medium",
            _sys(credit_decision=True),
            {},
            None,
            "bank",
            {"model", "data_governance", "cybersecurity", "legal_compliance", "ethics"}
            | {"third_party", "supply_chain"},
            {"third_party": "unknown_assume_applies"},
        ),
        # flags override the record and the facts
        (
            "medium",
            _sys(personal_data="special"),
            {"personal_data": False, "third_party_model": True, "dependencies": False},
            {"facts": [{"kind": "file"}]},
            "bank",
            {"model", "data_governance", "cybersecurity", "legal_compliance", "third_party"},
            {
                "ethics": "no_customer_decision_no_personal_data",
                "supply_chain": "no_dependency_signal",
            },
        ),
        (
            "low",
            _sys(),
            {},
            None,
            "bank",
            {"model", "data_governance", "cybersecurity", "legal_compliance"},
            {"third_party": "low_core_only", "reputation": "low_core_only"},
        ),
        (
            "low",
            _sys(personal_data="pseudonymised"),
            {},
            None,
            "bank",
            {"model", "data_governance", "cybersecurity", "legal_compliance", "ethics"},
            {"supply_chain": "low_core_only"},
        ),
    ],
)
def test_plan_rules(
    outcome: str,
    system: dict[str, Any],
    flags: dict[str, Any],
    facts: Any,
    institution: str,
    applying: set[str],
    reasons: dict[str, str],
) -> None:
    p = orch.plan(system, outcome, flags, facts, institution=institution)
    got = _applies(p)
    assert {d for d, (a, _) in got.items() if a} == applying
    for dim, reason in reasons.items():
        assert got[dim][1] == reason, dim
    assert not p.blocked
    assert [i.dimension_id for i in p.items][-1] == "legal_compliance"  # reads the others: last
    assert len(p.items) == 8


@pytest.mark.parametrize(
    ("outcome", "blocked"),
    [
        (None, "classification_required"),
        ("prohibited", "prohibited"),
        ("not_system", "not_system"),
        ("weird", "classification_required"),
    ],
)
def test_plan_blocked(outcome: str | None, blocked: str) -> None:
    p = orch.plan(_sys(), outcome, {}, None)
    assert p.blocked == blocked and not p.applicable()


def test_plan_agents_and_budget() -> None:
    live = orch.LiveAgent(
        "model-checker", "3", {"harness": {"loop": {"mode": "loop", "budget_tokens": 30000}}}
    )
    big = orch.LiveAgent("x", "1", {"harness": {"loop": {"budget_tokens": 10**9}}})
    p = orch.plan(_sys(), "high_self", {}, None, catalog=Cat({"model": live, "ethics": big}))
    items = {i.dimension_id: i for i in p.items}
    assert items["model"].agent == "model-checker@3" and items["model"].budget_tokens == 30000
    from supervisor.factory import caps

    assert items["ethics"].budget_tokens == caps.LOOP_BUDGET_MAX  # inside the platform cap
    assert items["cybersecurity"].agent == "rule" and items["cybersecurity"].budget_tokens == 0
    assert p.budget.total_tokens == 8 * caps.LOOP_BUDGET_DEFAULT
    # the null catalogue: every type is a rule item; the plan is stable (same hash twice)
    q = orch.plan(_sys(), "high_self", {}, None)
    assert {i.agent for i in q.items} == {"rule"}
    assert q.plan_hash == orch.plan(_sys(), "high_self", {}, None).plan_hash != p.plan_hash
    assert '"agent_seconds"' in json.dumps(p.to_dict())


# ------------------------------------------------------------------ the rule runner


def test_rule_runner_report_is_valid(orchon: Console) -> None:
    c = orchon
    sid = _ready(c)
    _all_required(c, "ok", ("model", "cybersecurity"))
    _result(c, "pii_canary", "fail")
    env = rd.Env.from_console(c.ctx)
    props = rd.propose(env, sid)
    for dim in rd.DIMENSION_IDS:
        req = orch.AgentRequest(
            "orc_t", sid, 1, dim, f"orc_t-{dim}", "rule-proposal", "1", None,
            {"proposal": props[dim], "prior": {}, "now": "2026-10-28T09:00:00Z"}, 30, 0,
        )  # fmt: skip
        raw = orch.RuleRunner().run(req)
        rep = AssessmentReportV1.model_validate(raw)
        assert rep.dimension_id == dim and rep.agent_id == "rule-proposal"
        want = {
            "model": "pass",
            "cybersecurity": "pass",
            "data_governance": "fail",
        }.get(dim)
        verdict = orch.worst_verdict([f.model_dump() for f in rep.findings])
        if want:
            assert verdict == want, dim
        n_checks = len(props[dim]["checks"])
        assert len(rep.findings) >= max(n_checks, 1)
        for f in rep.findings:  # one finding per mapped pack, the pack result is the evidence
            if f.checklist_id.startswith("pack:") and f.verdict in ("pass", "fail"):
                assert f.evidence and f.evidence[0].kind == "pack"
    # no mapped item: one question for a person, never a pass
    rep = orch.RuleRunner().run(
        orch.AgentRequest("o", sid, 1, "reputation", "o-rep", "rule-proposal", "1", None,
                          {"proposal": props["reputation"], "prior": {}}, 30, 0)
    )  # fmt: skip
    assert [f["verdict"] for f in rep["findings"]] == ["question"]


@pytest.mark.parametrize(
    ("verdicts", "worst"),
    [
        (["pass", "pass"], "pass"),
        (["pass", "question"], "question"),
        (["pass", "question", "fail"], "fail"),
        (["not_applicable", "pass"], "pass"),
        (["not_applicable"], "not_applicable"),
        ([], "question"),
    ],
)
def test_conflict_rule_worst_wins(verdicts: list[str], worst: str) -> None:
    assert orch.worst_verdict([{"verdict": v} for v in verdicts]) == worst


# ------------------------------------------------------------------ the run


def test_run_end_to_end(orchon: Console) -> None:
    c = orchon
    sid = _ready(c)
    _all_required(c, "ok", ("model", "cybersecurity", "supply_chain"))
    run = orch.run(c.ctx, sid, 1)
    assert run.status == "done" and run.attempt_n == 1 and len(run.summary) <= 300
    items = _items(run)
    assert set(items) == ALL8 and all(i["applies"] for i in items.values())
    assert items["model"]["verdict"] == "pass" and items["model"]["proposed_status"] == "pass"
    assert items["legal_compliance"]["verdict"] == "question"  # a person decides
    rows = _rows(c, sid)
    assert all(r["status"] != "pass" for r in rows.values())  # NEVER pass
    assert rows["model"]["status"] == "in_progress"
    assert rows["model"]["report_ref"] == f"{run.run_id}-model"
    assert rows["model"]["assessed_by"] == "rule"
    assert f"report:{run.run_id}-model" in rows["model"]["evidence_json"]
    # the report file, its sha, and it validates
    base = Path(c.ctx.settings.data_dir) / "assessments" / sid / "1"
    raw = (base / "model.json").read_bytes()
    assert hashlib.sha256(raw).hexdigest() == items["model"]["report_sha256"]
    AssessmentReportV1.model_validate(json.loads(raw))
    assert (base / "duties_prefill.json").is_file()
    # the person confirms with the existing C2 action
    out = rd.confirm_proposal(rd.Env.from_console(c.ctx), CREATOR, c.ctx.systems.get(sid), "model")
    assert out["to"] == "pass" and _rows(c, sid)["model"]["status"] == "pass"
    # chain record: ids, hashes and integers only
    recs = [r for r in _chain(c) if r[0] == "orchestrator_run"]
    assert len(recs) == 1
    pay = recs[0][2]
    assert pay["plan_hash"] == run.plan_hash and pay["n_applicable"] == 8
    assert "items" not in pay and not _has_float(pay)
    # an attempt that exists is refused; a new start is attempt 2
    with pytest.raises(orch.OrchestratorError, match="attempt_exists"):
        orch.run(c.ctx, sid, 1)
    assert orch.run(c.ctx, sid, 2).attempt_n == 2


def _chain(c: Console) -> list[tuple[str, str, dict[str, Any]]]:
    out: list[tuple[str, str, dict[str, Any]]] = []
    for x in sorted(c.ctx.tables.query("chain_entry", {}), key=lambda e: (e["lane"], e["seq"])):
        (row,) = c.ctx.tables.query("chain_payload", {"lane": x["lane"], "seq": x["seq"]})
        p = json.loads(row["payload"]) if isinstance(row["payload"], str) else row["payload"]
        out.append((x["record_type"], str(x.get("record_ref", "")), p))
    return out


def _has_float(value: Any) -> bool:
    if isinstance(value, float):
        return True
    if isinstance(value, Mapping):
        return any(_has_float(v) for v in value.values())
    if isinstance(value, list):
        return any(_has_float(v) for v in value)
    return False


def test_onboard_log_rows(orchon: Console, monkeypatch: pytest.MonkeyPatch) -> None:
    c = orchon
    sid = _ready(c, "low")
    run = orch.run(c.ctx, sid, 1)
    rows = [
        r for r in c.ctx.tables.query("onboard_log", {"node_id": sid}) if r["step"] == "orchestrate"
    ]
    whats = [r["what"] for r in rows]
    assert any(w.startswith("plan ") for w in whats)
    assert any("model: start" in w for w in whats)
    assert any(w.startswith("run done") for w in whats)
    assert all(r["by_kind"] == "rule" and r["attempt_n"] == 1 for r in rows)
    assert run.status == "done"


def test_hitl_high_fail_stops_the_type(orchon: Console) -> None:
    c = orchon
    sid = _ready(c)
    _result(c, "pii_canary", "fail")
    run = orch.run(c.ctx, sid, 1)
    it = _items(run)["data_governance"]
    assert it["status"] == "needs_person" and it["verdict"] == "fail"
    assert it["stop_point"].startswith("high_fail:pack:pii_canary") and it["needs_person"]
    assert _rows(c, sid)["data_governance"]["status"] == "fail"
    assert run.status == "done"  # the other types still ran
    assert _items(run)["model"]["status"] == "done"
    # a low-severity (optional) fail is not a stop point: verdict question, no stop
    sid2 = _ready_second(c)
    _result(c, "paraphrase_consistency", "fail", run="opt")
    r2 = orch.run(c.ctx, sid2, 1)
    assert _items(r2)["model"]["stop_point"] == ""


def _ready_second(c: Console) -> str:
    sid = _system(c, name="Second system")
    c.ctx.systems.link(sid, "agent", AGENT, CREATOR)
    _classify(c, sid, "high_self")
    return sid


def test_definition_approval_point_stops(orchon: Console) -> None:
    c = orchon
    sid = _ready(c)
    _all_required(c, "ok", ("model",))
    live = orch.LiveAgent(
        "model-checker",
        "1",
        {
            "checklist": [{"id": "pack:truthfulqa_vi", "severity": "low"}],
            "harness": {"hitl": {"approval_points": [{"kind": "verdict", "ref": "pass"}]}},
        },
    )
    # a partial definition is no real agent: the rule runner builds the report (F3 needs a full one)
    run = orch.run(c.ctx, sid, 1, catalog=Cat({"model": live}), runner=orch.RuleRunner())
    it = _items(run)["model"]
    assert it["agent"] == "model-checker@1" and it["status"] == "needs_person"
    assert it["stop_point"] == "approval_point:pass"
    # a stop point is never recorded as a pass proposal
    assert _rows(c, sid)["model"]["status"] == "fail"


class _Slow:
    def __init__(self, delay: float, only: str = "model") -> None:
        self.delay, self.only, self.rule = delay, only, orch.RuleRunner()

    def run(self, request: orch.AgentRequest) -> dict[str, Any]:
        if request.dimension_id == self.only:
            time.sleep(self.delay)
        return self.rule.run(request)


def _wait_running(c: Console, sid: str, dim: str = "model") -> None:
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        run = orch.latest(c.ctx, sid)
        if run and any(i["dimension_id"] == dim and i["status"] == "running" for i in run.items):
            return
        time.sleep(0.02)
    raise AssertionError(f"{dim} never ran")


def test_ux5_panel_shows_live_progress(orchon: Console, monkeypatch: pytest.MonkeyPatch) -> None:
    c = orchon
    monkeypatch.setattr(c.ctx.settings, "console_ux5", True)
    sid = _ready(c)
    orch.start(
        c.ctx, sid, CREATOR, background=True, runner=_Slow(1.0), budget=orch.Budget(rule_seconds=5)
    )
    _wait_running(c, sid)
    html = c.get(f"/console/systems/{sid}/orchestrate?lang=en", user=CREATOR).text
    assert 'data-orch="progress"' in html and 'role="progressbar"' in html
    assert 'hx-trigger="every 2s"' in html and "was=run" in html
    assert 'data-orch-step="model" data-status="running"' in html
    assert "Assessing: Model risk" in html and 'data-orch="pct">0%' in html
    assert 'data-act="orch-brief"' not in html  # the brief comes when the run ends
    orch.join(sid)
    # the first poll after the end reloads the rows once and offers the brief
    done = c.get(f"/console/systems/{sid}/orchestrate?lang=en&was=run", user=CREATOR).text
    assert 'data-orch="auto-reload"' in done and 'hx-target="#tab-body"' in done
    # only the tab of the full system page goes into #tab-body (no page in the page)
    reload_tag = done.split('data-orch="auto-reload"', 1)[1][:300]
    assert 'hx-select="#tab-body &gt; *"' in reload_tag or 'hx-select="#tab-body > *"' in reload_tag
    assert 'hx-trigger="every 2s"' not in done and 'data-orch="pct">100%' in done
    assert 'data-act="orch-brief"' in done and "/brief?lang=en" in done
    assert 'data-status="running"' not in done
    # any later answer (no was=run) does not reload again
    later = c.get(f"/console/systems/{sid}/orchestrate?lang=en", user=CREATOR).text
    assert 'data-orch="auto-reload"' not in later and 'data-act="orch-brief"' in later
    vi = c.get(f"/console/systems/{sid}/orchestrate?lang=vi", user=CREATOR).text
    assert "Xem bản tóm tắt" in vi


def test_brief_report(orchon: Console, monkeypatch: pytest.MonkeyPatch) -> None:
    c = orchon
    monkeypatch.setattr(c.ctx.settings, "console_ux5", True)
    sid = _ready(c)
    _all_required(c, "ok", ("model",))
    _result(c, "pii_canary", "fail")
    run = orch.run(c.ctx, sid, 1)
    base = f"/console/systems/{sid}/orchestrate/{run.run_id}/brief"
    part = c.get(f"{base}?lang=en", user=CREATOR, headers={"HX-Request": "true"})
    assert part.status_code == 200, part.text[:300]
    h = part.text
    assert 'data-orch="brief-body"' in h and "<html" not in h.lower()
    assert "Assessment summary, attempt 1" in h and "High risk, self-assessed" in h
    for dim in rd.DIMENSION_IDS:
        assert f'data-orch-brief-dim="{dim}"' in h
    assert "Rule-based check" in h and f"/v1/orchestrate/{run.run_id}/reports/model" in h
    assert 'data-act="orch-brief-page"' in h and "Not legal advice" in h
    # the totals are the sums of the stored reports
    reps = [
        json.loads(p.read_text(encoding="utf-8"))
        for p in orch.report_dir(c.ctx.settings, sid, 1).glob("*.json")
        if p.stem in rd.DIMENSION_IDS
    ]
    passed = sum(r["summary"]["passed"] for r in reps)
    failed = sum(r["summary"]["failed"] for r in reps)
    assert passed >= 1 and f"{passed} pass" in h and f"{failed} fail" in h
    if failed:
        assert 'data-orch="brief-fails"' in h
    # as a page, with ?dim= opening that type
    page = c.get(f"{base}?lang=en&dim=model", user=CREATOR)
    assert page.status_code == 200 and "<html" in page.text.lower()
    assert 'data-act="orch-brief-page"' not in page.text
    blk = page.text.split('data-orch-brief-dim="model"', 1)[1][:200]
    assert "<details open" in blk
    vi = c.get(f"{base}?lang=vi", user=CREATOR, headers={"HX-Request": "true"}).text
    assert "Tóm tắt đánh giá, lần chạy 1" in vi
    # the Open report link of the table goes to the brief page
    tab = c.get(f"/console/systems/{sid}?tab=riskdim&lang=en", user=CREATOR).text
    assert f"{base}?dim=model" in tab
    # out of scope, unknown run, a run of another system, a bad id: 400, never 500
    assert c.get(f"{base}?lang=en", user=VIEWER).status_code == 400
    assert c.get(f"/console/systems/{sid}/orchestrate/orc_nope/brief").status_code == 400
    other = _ready_second(c)
    assert c.get(f"/console/systems/{other}/orchestrate/{run.run_id}/brief").status_code == 400
    assert c.get(f"/console/systems/{sid}/orchestrate/a%20b/brief").status_code == 400


def test_brief_off_path(on: Console) -> None:
    sid = _system(on)
    assert on.get(f"/console/systems/{sid}/orchestrate/orc_x/brief").status_code == 400


def test_demo_pace_waits_before_each_type(orchon: Console, monkeypatch: pytest.MonkeyPatch) -> None:
    c = orchon
    sid = _ready(c)
    waits: list[float] = []
    monkeypatch.setattr(orch.time, "sleep", waits.append)
    run = orch.run(c.ctx, sid, 1)
    assert waits == []  # default 0: no pause
    monkeypatch.setattr(c.ctx.settings, "orch_demo_pace_ms", 400)
    run2 = orch.run(c.ctx, sid, 2)
    applicable = sum(1 for i in run2.items if i["applies"])
    assert waits == [0.4] * applicable and run.status == run2.status == "done"


def test_demo_pace_setting_bounds(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SUPERVISOR_ENV_FILE", "/dev/null")
    monkeypatch.setenv("ORCH_DEMO_PACE_MS", "1500")
    assert load_settings().orch_demo_pace_ms == 1500
    monkeypatch.setenv("ORCH_DEMO_PACE_MS", "9000")
    with pytest.raises(Exception):  # noqa: B017 - above the cap of 5000
        load_settings()


def test_budget_time_cut(orchon: Console) -> None:
    c = orchon
    sid = _ready(c)
    started = time.monotonic()
    run = orch.run(c.ctx, sid, 1, runner=_Slow(3.0), budget=orch.Budget(rule_seconds=1))
    assert time.monotonic() - started < 2.9 * 1 + 2  # not 3 s per slow call
    it = _items(run)["model"]
    assert it["status"] == "budget_exceeded" and "time limit" in it["note"]
    assert it["report_ref"] == "" and _rows(c, sid)["model"]["status"] == "not_started"
    assert _items(run)["data_governance"]["status"] == "done"
    assert run.status == "done"
    assert not (Path(c.ctx.settings.data_dir) / "assessments" / sid / "1" / "model.json").exists()


def test_budget_total_and_tokens(orchon: Console) -> None:
    c = orchon
    sid = _ready(c)
    run = orch.run(c.ctx, sid, 1, budget=orch.Budget(total_seconds=0))
    assert all(i["status"] == "budget_exceeded" for i in run.items if i["applies"])
    # tokens: a live agent whose report says it used more than its budget is cut
    sid2 = _ready_second(c)

    class Heavy:
        def run(self, request: orch.AgentRequest) -> dict[str, Any]:
            rep = orch.RuleRunner().run(request)
            rep["harness_trace"]["context"]["tokens_used"] = request.budget_tokens + 1
            return rep

    live = orch.LiveAgent("heavy", "1", {"harness": {"loop": {"budget_tokens": 5000}}})
    r2 = orch.run(c.ctx, sid2, 1, catalog=Cat({"model": live}), runner=Heavy())
    it = _items(r2)["model"]
    assert it["status"] == "budget_exceeded" and "tokens" in it["note"]
    assert _items(r2)["ethics"]["status"] == "done"  # the rule items are not token-limited


def test_runner_error_and_invalid_report_fail_the_item(orchon: Console) -> None:
    c = orchon
    sid = _ready(c)

    class Bad:
        def run(self, request: orch.AgentRequest) -> dict[str, Any]:
            if request.dimension_id == "model":
                raise RuntimeError("boom")
            rep = orch.RuleRunner().run(request)
            if request.dimension_id == "ethics":
                rep["findings"][0]["verdict"] = "pass"  # pass without evidence
                rep["findings"][0]["evidence"] = []
                rep["summary"] = {
                    "total": 1,
                    "passed": 1,
                    "failed": 0,
                    "not_applicable": 0,
                    "questions": 0,
                }
                rep["findings"] = rep["findings"][:1]
            return rep

    run = orch.run(c.ctx, sid, 1, runner=Bad())
    assert _items(run)["model"]["status"] == "failed"
    assert (
        _items(run)["ethics"]["status"] == "failed" and "invalid" in _items(run)["ethics"]["note"]
    )
    assert _items(run)["cybersecurity"]["status"] == "done"
    assert run.status == "done"


def test_never_writes_pass_even_for_an_all_pass_agent(orchon: Console) -> None:
    c = orchon
    sid = _ready(c)

    class AllPass:
        def run(self, request: orch.AgentRequest) -> dict[str, Any]:
            f = {
                "finding_id": "f1",
                "checklist_id": "c1",
                "verdict": "pass",
                "evidence": [{"kind": "fact", "ref": "fact:abc"}],
                "rationale": "ok",
                "confidence": "high",
            }
            rep = orch.RuleRunner().run(request)
            rep["findings"] = [f]
            rep["summary"] = {
                "total": 1,
                "passed": 1,
                "failed": 0,
                "not_applicable": 0,
                "questions": 0,
            }
            return rep

    run = orch.run(c.ctx, sid, 1, runner=AllPass())
    assert all(i["verdict"] == "pass" for i in run.items)
    assert all(r["status"] != "pass" for r in _rows(c, sid).values())
    assert {r["status"] for r in _rows(c, sid).values()} == {"in_progress"}
    env = rd.Env.from_console(c.ctx)
    with pytest.raises(orch.OrchestratorError, match="pass_needs_person"):
        orch._write_status(env, c.ctx.systems.get(sid), "model", "pass", "rule", "r", [], "n")


def test_legal_compliance_reads_the_others(orchon: Console) -> None:
    c = orchon
    sid = _ready(c)
    _result(c, "pii_canary", "fail")
    run = orch.run(c.ctx, sid, 1)
    items = _items(run)
    assert [i["dimension_id"] for i in run.items][-1] == "legal_compliance"
    legal = json.loads(
        (
            Path(c.ctx.settings.data_dir) / "assessments" / sid / "1" / "legal_compliance.json"
        ).read_text()
    )
    reads = {
        f["checklist_id"]: f for f in legal["findings"] if f["checklist_id"].startswith("reads:")
    }
    assert reads["reads:data_governance"]["verdict"] == "fail"
    assert (
        items["legal_compliance"]["verdict"] == "fail" and items["legal_compliance"]["needs_person"]
    )


def test_waived_row_is_left_alone_and_na_is_written(orchon: Console) -> None:
    c = orchon
    sid = _ready(c, "low", personal_data="none")
    env = rd.Env.from_console(c.ctx)
    system = c.ctx.systems.get(sid)
    rd.waive(env, "approver.em", system, "model", "The bank accepts this for the pilot.")
    run = orch.run(c.ctx, sid, 1)
    rows = _rows(c, sid)
    assert rows["model"]["status"] == "waived"
    assert _items(run)["model"]["status_written"] == ""
    assert rows["reputation"]["status"] == "not_applicable"
    assert "core risk types only" in rows["reputation"]["note"]
    assert _items(run)["reputation"]["status"] == "not_applicable"


def test_duties_prefill(orchon: Console) -> None:
    c = orchon
    sid = _ready(c)
    _all_required(c, "ok", ("model", "data_governance"))
    run = orch.run(c.ctx, sid, 1)
    doc = orch.read_duties_prefill(c.ctx.settings, sid)
    assert doc is not None and doc["run_id"] == run.run_id and doc["system_id"] == sid
    covered = {x["dimension_id"]: x for x in doc["covered"]}
    assert set(covered) == {"model", "data_governance"}
    assert covered["model"]["articles"] == list(rd.load_config().get("model").articles)
    assert covered["model"]["controls"] and covered["model"]["confirmed"] is False
    assert {o["dimension_id"] for o in doc["open"]} == ALL8 - set(covered)
    assert doc["banner"].startswith("Not legal advice") and not _has_float(doc)
    # with the state the entry becomes confirmed once a person sets pass
    again = orch.read_duties_prefill(c.ctx.settings, sid, c.ctx.state)
    assert again is not None and not any(x["confirmed"] for x in again["covered"])
    rd.confirm_proposal(rd.Env.from_console(c.ctx), CREATOR, c.ctx.systems.get(sid), "model")
    again = orch.read_duties_prefill(c.ctx.settings, sid, c.ctx.state)
    assert again is not None
    assert {x["dimension_id"]: x["confirmed"] for x in again["covered"]}["model"] is True
    # the newest attempt wins; no file means None, never an error
    orch.run(c.ctx, sid, 2)
    newest = orch.read_duties_prefill(c.ctx.settings, sid)
    assert newest is not None and newest["attempt_n"] == 2
    assert orch.read_duties_prefill(c.ctx.settings, "no-such-system") is None


def test_pending_class_blocks_by_default(orchon: Console) -> None:
    c = orchon
    assert c.ctx.settings.assess_pending_class is False
    sid = _system(c)
    _classify(c, sid, "medium", approved=False)
    assert orch.classification_outcome(c.ctx, sid) is None
    r = _api(c, "POST", f"/v1/systems/{sid}/orchestrate")
    assert r.status_code == 400 and "plan_blocked" in r.text and "approved classification" in r.text


def test_pending_class_counts_with_the_demo_flag(
    orchon: Console, monkeypatch: pytest.MonkeyPatch
) -> None:
    c = orchon
    monkeypatch.setattr(c.ctx.settings, "assess_pending_class", True)
    sid = _system(c)
    assert orch.classification_outcome(c.ctx, sid) is None  # nothing saved: still blocked
    add_agent(c.runtime.adapters, AGENT)
    c.ctx.systems.link(sid, "agent", AGENT, CREATOR)
    _classify(c, sid, "medium", approved=False)
    assert orch.classification_outcome(c.ctx, sid) == "medium"
    r = _api(c, "POST", f"/v1/systems/{sid}/orchestrate")
    assert r.status_code == 202, r.text
    orch.join(sid)
    assert _api(c, "GET", f"/v1/systems/{sid}/orchestrate").json()["status"] == "done"


def test_demo_flag_keeps_an_approved_class(
    orchon: Console, monkeypatch: pytest.MonkeyPatch
) -> None:
    c = orchon
    monkeypatch.setattr(c.ctx.settings, "assess_pending_class", True)
    sid = _ready(c, "high_self")
    assert orch.classification_outcome(c.ctx, sid) == "high_self"


# ------------------------------------------------------------------ API


def test_api_plan_blocked_and_run_flow(orchon: Console) -> None:
    c = orchon
    sid = _system(c)
    r = _api(c, "POST", f"/v1/systems/{sid}/orchestrate")
    assert r.status_code == 400 and "plan_blocked" in r.text and "classification" in r.text
    _classify(c, sid, "prohibited")
    r = _api(c, "POST", f"/v1/systems/{sid}/orchestrate")
    assert r.status_code == 400 and "prohibited" in r.text
    assert _api(c, "GET", f"/v1/systems/{sid}/orchestrate").status_code == 404  # no run yet
    sid2 = _ready(c, "medium")
    r = _api(c, "POST", f"/v1/systems/{sid2}/orchestrate")
    assert r.status_code == 202, r.text
    body = r.json()
    assert body["attempt_n"] == 1 and body["run_id"].startswith("orc_")
    orch.join(sid2)
    got = _api(c, "GET", f"/v1/systems/{sid2}/orchestrate").json()
    assert got["run_id"] == body["run_id"] and got["status"] == "done" and got["items"]
    assert (
        _api(c, "GET", f"/v1/orchestrate/{body['run_id']}").json()["plan_hash"] == body["plan_hash"]
    )
    rep = _api(c, "GET", f"/v1/orchestrate/{body['run_id']}/reports/model")
    assert rep.status_code == 200 and rep.json()["dimension_id"] == "model"
    assert _api(c, "GET", f"/v1/orchestrate/{body['run_id']}/reports/ethics").status_code in (
        200,
        404,
    )
    assert _api(c, "GET", f"/v1/orchestrate/{body['run_id']}/reports/bogus").status_code == 404
    assert _api(c, "GET", "/v1/orchestrate/orc_nope").status_code == 404
    # audit rows: two console_action rows for the POST
    acts = [
        r
        for r in c.ctx.tables.query("console_action", {})
        if str(r.get("path", "")).endswith("/orchestrate") and r.get("method") == "POST"
    ]
    assert len(acts) >= 2


def test_run_in_progress(orchon: Console) -> None:
    c = orchon
    sid = _ready(c)
    orch.set_catalog(orch.NullCatalog())
    slow = _Slow(1.2)
    run = orch.start(
        c.ctx, sid, CREATOR, background=True, runner=slow, budget=orch.Budget(rule_seconds=5)
    )
    assert run.status in ("queued", "running")
    r = _api(c, "POST", f"/v1/systems/{sid}/orchestrate")
    assert r.status_code == 400 and "run_in_progress" in r.text
    r = c.post(f"/console/systems/{sid}/orchestrate", {}, user=CREATOR)
    assert r.status_code == 400 and "run_in_progress" in r.text
    orch.join(sid)
    assert orch.get(c.ctx, run.run_id).status == "done"  # type: ignore[union-attr]
    # after it ended the system can run again
    assert _api(c, "POST", f"/v1/systems/{sid}/orchestrate").status_code == 202
    orch.join(sid)


def test_stale_running_row_is_closed(orchon: Console) -> None:
    c = orchon
    sid = _ready(c)
    first = orch.run(c.ctx, sid, 1)
    orch._save(c.ctx, first.run_id, {"status": "running"})  # a restart left it running
    nxt = orch.start(c.ctx, sid, CREATOR, background=False)
    assert nxt.attempt_n == 2 and nxt.status == "done"
    assert orch.get(c.ctx, first.run_id).status == "failed"  # type: ignore[union-attr]


def test_rbac(orchon: Console) -> None:
    c = orchon
    sid = _ready(c, "low")
    assert _api(c, "POST", f"/v1/systems/{sid}/orchestrate", user=VIEWER).status_code == 403
    assert c.post(f"/console/systems/{sid}/orchestrate", {}, user=VIEWER).status_code == 403
    assert _api(c, "POST", f"/v1/systems/{sid}/orchestrate", user=CREATOR).status_code == 202
    orch.join(sid)
    assert _api(c, "GET", f"/v1/systems/{sid}/orchestrate", user=VIEWER).status_code != 403
    assert c.get(f"/console/systems/{sid}/orchestrate", user=VIEWER).status_code != 403
    # a system outside the caller's scope answers 404
    assert _api(c, "GET", "/v1/systems/nope/orchestrate", user=VIEWER).status_code == 404


# ------------------------------------------------------------------ console


def test_htmx_panel_and_button(orchon: Console) -> None:
    c = orchon
    sid = _ready(c)
    tab = c.get(f"/console/systems/{sid}?tab=riskdim&lang=en").text
    assert 'id="orch-panel"' in tab and 'data-act="orch-run"' in tab
    assert 'data-act="rd-reassess"' not in tab  # the placeholder is replaced
    assert "No assessment yet." in tab
    r = c.post(f"/console/systems/{sid}/orchestrate", {}, user=CREATOR)
    assert r.status_code == 200, r.text[:300]
    assert 'id="orch-panel"' in r.text and "Assessment started." in r.text
    orch.join(sid)
    panel = c.get(f"/console/systems/{sid}/orchestrate?lang=en", user=CREATOR)
    assert panel.status_code == 200
    html = panel.text
    assert 'data-orch-dim="model"' in html and 'data-orch-dim="legal_compliance"' in html
    assert "/reports/model" in html and "Budget used" in html and "Plan ID" in html
    assert 'hx-trigger="every 2s"' not in html  # finished: no more polling
    assert "Not legal advice" in html
    vi = c.get(f"/console/systems/{sid}/orchestrate?lang=vi", user=CREATOR).text
    assert "Chạy đánh giá" in vi
    # a viewer sees the panel without the button
    v = c.get(f"/console/systems/{sid}/orchestrate?lang=en", user=VIEWER).text
    assert 'data-act="orch-run"' not in v
    # a plain form post (no HX header, no Origin) is refused with 400, never 500
    assert (
        c.post(f"/console/systems/{sid}/orchestrate", {}, user=CREATOR, htmx=False).status_code
        == 400
    )


def test_panel_polls_while_running(orchon: Console) -> None:
    c = orchon
    sid = _ready(c)
    orch.start(
        c.ctx, sid, CREATOR, background=True, runner=_Slow(1.0), budget=orch.Budget(rule_seconds=5)
    )
    html = c.get(f"/console/systems/{sid}/orchestrate?lang=en", user=CREATOR).text
    assert 'hx-trigger="every 2s"' in html and 'data-act="orch-run"' not in html
    orch.join(sid)


# --------------------------------------------------------------------------- plain wording


def test_every_reason_code_has_a_sentence_and_both_labels() -> None:
    from supervisor.console.i18n_orch import ORCH

    outcomes = (*orch.OUTCOMES, None)
    seen: set[str] = set()
    cfg = rd.load_config()
    for outcome in outcomes:
        for flags in ({}, {"customer_decision": True}, {"third_party_model": False}):
            for institution in ("bank", "other"):
                p = orch.plan(
                    {"system_id": "s", "user_segment": "customer"},
                    outcome,
                    flags,
                    None,
                    institution=institution,
                    cfg=cfg,
                )
                seen.update(i.reason for i in p.items)
    assert seen and seen <= set(orch.REASON_EN)
    for code in orch.REASON_EN:
        en, vi = ORCH[f"orch_reason_{code}"]
        assert en == orch.REASON_EN[code] and vi.strip()


def test_finding_rationales_are_plain_sentences() -> None:
    def prop(state: str, required: bool) -> dict[str, Any]:
        ptr = ["pack:truthfulqa_vi:r1:agent"] if state in ("ok", "fail") else []
        chk = {"kind": "pack", "id": "truthfulqa_vi", "required": required, "state": state}
        return {"checks": [{**chk, "pointers": ptr}]}

    def why(state: str, required: bool) -> str:
        return orch.rule_findings("model", prop(state, required), {})[0]["rationale"]

    assert why("missing", True) == "Required test truthfulqa_vi has not been run yet."
    assert why("missing", False) == "Optional test truthfulqa_vi has not been run yet."
    assert why("ok", True) == "Required test truthfulqa_vi passed."
    assert why("fail", True) == "Required test truthfulqa_vi failed."
    assert "out of date" in why("stale", True)
    legal = orch.rule_findings(
        "legal_compliance", {"checks": []}, {"model": {"report_id": "r", "verdict": "question"}}
    )
    texts = [f["rationale"] for f in legal]
    assert "Model risk is still open, so legal compliance stays open." in texts
    assert "No automated test covers this risk type. You decide it at the Duties step." in texts


# ------------------------------------------------------------------ W1: real-model wiring


def test_w1_rule_items_carry_agent_kind_and_the_off_path_is_unchanged(orchon: Console) -> None:
    c = orchon
    sid = _ready(c)
    assert c.ctx.settings.orch_run_draft_agents is False
    run = orch.run(c.ctx, sid, 1)
    applicable = [i for i in run.items if i["applies"]]
    assert applicable and {i["agent_kind"] for i in run.items} == {"rule"}
    assert {i["agent"] for i in applicable} == {"rule"}
    assert all("agent_kind" in i for i in run.plan["items"])
    assert all("model_error" not in i for i in run.items)


def test_w1_time_budget_comes_from_the_settings(
    orchon: Console, monkeypatch: pytest.MonkeyPatch
) -> None:
    c = orchon
    assert orch.settings_budget(c.ctx.settings) == orch.Budget()  # defaults = the old constants
    monkeypatch.setattr(c.ctx.settings, "orch_agent_seconds", 77)
    monkeypatch.setattr(c.ctx.settings, "orch_total_seconds", 555)
    sid = _ready(c)
    run = orch.run(c.ctx, sid, 1)
    assert run.budget["agent_seconds"] == 77 and run.budget["total_seconds"] == 555
    assert run.budget["rule_seconds"] == orch.RULE_SECONDS  # the rule runner is unchanged
    explicit = orch.run(c.ctx, sid, 2, budget=orch.Budget(agent_seconds=9))
    assert explicit.budget["agent_seconds"] == 9  # an explicit budget still wins


def test_w1_runner_gets_settings_and_a_diag_and_a_model_failure_is_in_the_note(
    orchon: Console,
) -> None:
    c = orchon
    sid = _ready(c)
    seen: dict[str, Any] = {}

    class Failing:
        def run(self, request: orch.AgentRequest) -> dict[str, Any]:
            rep = orch.RuleRunner().run(request)
            if request.dimension_id == "model":
                seen["settings"] = request.inputs["settings"]
                request.inputs["diag"].update(
                    {
                        "model_calls": 3,
                        "model_calls_failed": 3,
                        "model_items_failed": 5,
                        "model_error": "LLMError: HTTP 400",
                    }
                )
            return rep

    draft_agent = orch.LiveAgent("model-draft", "0.2-draft", {"checklist": []}, "draft")
    run = orch.run(c.ctx, sid, 1, catalog=Cat({"model": draft_agent}), runner=Failing())
    assert seen["settings"] is c.ctx.settings
    it = _items(run)["model"]
    assert it["agent_kind"] == "draft" and it["agent"] == "model-draft@0.2-draft"
    assert it["status"] == "done"  # the run goes on; the report is stored
    assert it["model_error"] == "LLMError: HTTP 400"
    assert it["note"] == (
        "The AI model failed on 3 of 3 calls (LLMError: HTTP 400). 5 item(s) were left open "
        "for a person. Check the model settings and run it again."
    )
    assert "model_error" not in _items(run)["data_governance"]  # rule items are not touched
    assert run.plan["items"][0]["agent_kind"] == "draft"


def test_w1_a_live_agent_without_a_model_says_so_in_plain_words(orchon: Console) -> None:
    c = orchon
    sid = _ready(c)
    live = orch.LiveAgent("model-live", "1", {"checklist": []})

    class NoModel:
        def run(self, request: orch.AgentRequest) -> dict[str, Any]:
            from supervisor.factory.runtime import MODEL_OFF_TEXT, AgentRuntimeError

            if request.dimension_id == "model":
                raise AgentRuntimeError("model_not_configured", MODEL_OFF_TEXT)
            return orch.RuleRunner().run(request)

    it = _items(orch.run(c.ctx, sid, 1, catalog=Cat({"model": live}), runner=NoModel()))["model"]
    assert it["status"] == "failed" and it["agent_kind"] == "live"
    assert it["note"].startswith("The AI model is not set up")
    assert "AgentRuntimeError" not in it["note"]


def test_w1_the_json_route_passes_the_factory_catalogue(
    orchon: Console, monkeypatch: pytest.MonkeyPatch
) -> None:
    c = orchon
    sid = _ready(c)
    asked: list[Any] = []
    draft_agent = orch.LiveAgent("model-draft", "0.1-draft", {"checklist": []}, "draft")

    def fake_for_console(ctx: Any) -> Cat:
        asked.append(ctx)
        return Cat({"model": draft_agent})

    from supervisor.factory import catalog as factory_catalog

    monkeypatch.setattr(factory_catalog, "for_console", fake_for_console)
    monkeypatch.setattr(orch, "RoutingRunner", lambda: orch.RuleRunner())
    r = _api(c, "POST", f"/v1/systems/{sid}/orchestrate")
    assert r.status_code == 202, r.text
    orch.join(sid)
    assert len(asked) == 1
    got = _api(c, "GET", f"/v1/systems/{sid}/orchestrate").json()
    assert {i["dimension_id"]: i["agent_kind"] for i in got["items"]}["model"] == "draft"


# ------------------------------------------------------------------ W3: executive findings

_W3_FACTS = {
    "version": 1,
    "nodes": ["n1"],
    "facts": [
        {
            "kind": "tool",
            "name": "transfer",
            "detail": "risk_class=money; approved=yes",
            "file": "code/tools.py",
            "line": 49,
        },
        {
            "kind": "autonomy",
            "name": "L3",
            "detail": "tools with side effects and no human approval step in code: transfer",
            "file": "code/tools.py",
            "line": 50,
        },
    ],
}


def _w3_exec_files(c: Console, sid: str) -> list[Path]:
    return sorted(orch.report_dir(c.ctx.settings, sid, 1).glob("*.exec.json"))


def _w3_run(
    c: Console, monkeypatch: pytest.MonkeyPatch, on: bool
) -> tuple[str, orch.OrchestratorRun]:
    monkeypatch.setattr(c.ctx.settings, "console_ux5", True)
    monkeypatch.setattr(c.ctx.settings, "orch_exec_findings", on)
    monkeypatch.setattr(orch, "facts_for", lambda ctx, system_id: _W3_FACTS)
    sid = _ready(c)
    return sid, orch.run(c.ctx, sid, 1)


def test_w3_exec_off_path_writes_nothing_and_ui_is_unchanged(
    orchon: Console, monkeypatch: pytest.MonkeyPatch
) -> None:
    c = orchon
    assert load_settings().orch_exec_findings is False and load_settings().orch_exec_llm is False
    sid, run = _w3_run(c, monkeypatch, False)
    assert _w3_exec_files(c, sid) == []
    base = f"/console/systems/{sid}/orchestrate/{run.run_id}/brief"
    h = c.get(f"{base}?lang=en", user=CREATOR, headers={"HX-Request": "true"}).text
    for marker in ("exec-bottom", "exec-key", "exec-all", "agent-kind", "g2-ex-card"):
        assert marker not in h
    assert "Rule-based check" in h and 'data-table="brief-findings"' in h
    tab = c.get(f"/console/systems/{sid}?tab=riskdim&lang=en", user=CREATOR).text
    assert 'data-orch="exec-top"' not in tab


def test_w3_exec_on_writes_sidecars_and_the_brief_shows_them(
    orchon: Console, monkeypatch: pytest.MonkeyPatch
) -> None:
    from supervisor.onboard import executive

    c = orchon
    sid, run = _w3_run(c, monkeypatch, True)
    files = _w3_exec_files(c, sid)
    assert {p.name for p in files} == {f"{d}.exec.json" for d in rd.DIMENSION_IDS}
    out_dir = orch.report_dir(c.ctx.settings, sid, 1)
    doc = executive.read(out_dir, "cybersecurity")
    assert doc and doc["writer"] == "rules" and doc["items"][0]["key"] == "money_tool_no_gate"
    # the report file and its hash are not touched by the sidecar
    item = _items(run)["cybersecurity"]
    raw = (out_dir / "cybersecurity.json").read_bytes()
    assert hashlib.sha256(raw).hexdigest() == item["report_sha256"]
    base = f"/console/systems/{sid}/orchestrate/{run.run_id}/brief"
    h = c.get(f"{base}?lang=en", user=CREATOR, headers={"HX-Request": "true"}).text
    assert 'data-orch="exec-bottom"' in h and "Bottom line" in h and "Key findings" in h
    assert "The agent can send payments (transfer)" in h
    assert "Why it matters" in h and "Next step" in h and "Who acts" in h
    assert "The system owner" in h and "code/tools.py:49" in h
    assert "Written by rules" in h and "Rule check" in h and 'data-orch="exec-all"' in h
    assert "All checks (" in h and 'data-table="brief-findings"' in h  # raw findings stay
    # the bottom line shows the same finding once, with all the types it applies to
    bottom = h.split('data-orch="exec-bottom"', 1)[1].split('data-orch="brief-kpis"', 1)[0]
    assert bottom.count('data-exec-item="money_tool_no_gate"') == 1
    assert "Applies to:" in bottom and bottom.count("g2-ex-card") <= 3 + 1
    vi = c.get(f"{base}?lang=vi", user=CREATOR, headers={"HX-Request": "true"}).text
    assert "Kết luận chính" in vi and "Phát hiện chính" in vi and "Tác tử có thể chuyển tiền" in vi
    page = c.get(f"{base}?lang=en", user=CREATOR)
    assert page.status_code == 200 and "exec-bottom" in page.text
    # the Result column of the table shows the top headline of the type
    tab = c.get(f"/console/systems/{sid}?tab=riskdim&lang=en", user=CREATOR).text
    cyber = tab.split('data-dimension="cybersecurity"', 1)[1].split("</tr>", 1)[0]
    assert 'data-orch="exec-top"' in cyber and 'data-rating="high"' in cyber
    assert "The agent can send payments" in cyber


def test_w3_exec_on_for_an_old_run_builds_on_the_fly(
    orchon: Console, monkeypatch: pytest.MonkeyPatch
) -> None:
    c = orchon
    sid, run = _w3_run(c, monkeypatch, False)
    assert _w3_exec_files(c, sid) == []
    monkeypatch.setattr(c.ctx.settings, "orch_exec_findings", True)
    base = f"/console/systems/{sid}/orchestrate/{run.run_id}/brief"
    h = c.get(f"{base}?lang=en", user=CREATOR, headers={"HX-Request": "true"}).text
    assert 'data-orch="exec-bottom"' in h and "Written by rules" in h
    assert _w3_exec_files(c, sid) == []  # shown, not stored


def test_w3_exec_failure_never_fails_the_run(
    orchon: Console, monkeypatch: pytest.MonkeyPatch
) -> None:
    from supervisor.onboard import executive

    def boom(*a: Any, **k: Any) -> Any:
        raise RuntimeError("boom")

    monkeypatch.setattr(executive, "build", boom)
    c = orchon
    sid, run = _w3_run(c, monkeypatch, True)
    assert run.status == "done" and _w3_exec_files(c, sid) == []
    assert all(i["status"] in ("done", "needs_person") for i in run.items if i["applies"])


class _W3Model:
    is_mock = False
    family = "fake"
    model_id = "fake-model-9"

    def __init__(self) -> None:
        self.calls = 0

    def complete_json(self, messages: Any, schema: Any, timeout_s: float) -> Any:
        self.calls += 1
        payload = json.loads(messages[1]["content"])
        for it in payload["items"]:
            if it["key"] == "money_tool_no_gate":
                it["headline"] = {
                    "en": "Payments (transfer) can run with no approval step in the code.",
                    "vi": "Thanh toán (transfer) có thể chạy mà mã không có bước phê duyệt.",
                }
        return payload


def test_w3_exec_llm_layer_is_off_by_default_and_labelled(
    orchon: Console, monkeypatch: pytest.MonkeyPatch
) -> None:
    import supervisor.adapters.factory as factory

    model = _W3Model()
    monkeypatch.setattr(factory, "make_chat_model", lambda settings: model)
    c = orchon
    monkeypatch.setattr(c.ctx.settings, "llm_base_url", "http://fake.invalid/v1")
    # the main flag on, the model layer off: no model call, writer rules
    sid, run = _w3_run(c, monkeypatch, True)
    assert model.calls == 0
    from supervisor.onboard import executive

    out_dir = orch.report_dir(c.ctx.settings, sid, 1)
    assert executive.read(out_dir, "cybersecurity")["writer"] == "rules"
    # both on: one call per risk type with items, writer ai:<model>, shown on screen
    monkeypatch.setattr(c.ctx.settings, "orch_exec_llm", True)
    run2 = orch.run(c.ctx, sid, 2)
    assert model.calls >= 1 and run2.status == "done"
    doc = executive.read(orch.report_dir(c.ctx.settings, sid, 2), "cybersecurity")
    assert doc["writer"] == "ai:fake-model-9"
    assert doc["items"][0]["headline"]["en"].startswith("Payments (transfer) can run")
    assert doc["items"][0]["status"] == "fail" and doc["items"][0]["severity"] == "high"
    h = c.get(
        f"/console/systems/{sid}/orchestrate/{run2.run_id}/brief?lang=en",
        user=CREATOR,
        headers={"HX-Request": "true"},
    ).text
    assert "AI-written (fake-model-9)" in h


def test_w1_facts_follow_the_node_id_in_the_tags(monkeypatch: pytest.MonkeyPatch) -> None:
    """A system registered from a scanned object has no component row; its tags name the node."""
    from types import SimpleNamespace

    from supervisor.factory.schemas import facts_v1
    from supervisor.onboard import facts as facts_mod

    asked: list[str] = []

    class FakeSvc:
        def __init__(self, *a: Any, **k: Any) -> None: ...

        def card(self, ref: str) -> str:
            asked.append(ref)
            return ref

    monkeypatch.setattr(facts_mod, "FactsService", FakeSvc)
    monkeypatch.setattr(
        facts_v1,
        "export_card",
        lambda ref: {"facts": [{"fact_id": f"f-{ref}", "kind": "tool"}] if ref == "inv_9" else []},
    )

    def ctx_for(tags: str, comps: list[dict[str, Any]]) -> Any:
        state = SimpleNamespace(
            query=lambda table, where: comps,
            get=lambda table, key: {"system_id": "S1", "tags": tags},
        )
        return SimpleNamespace(
            settings=SimpleNamespace(onboard_facts=True), state=state, tables=None, clock=None
        )

    got = orch.facts_for(ctx_for('{"node_id": "inv_9", "kind": "app"}', []), "S1")
    assert got is not None and got["nodes"] == ["inv_9"] and got["facts"][0]["fact_id"] == "f-inv_9"
    assert asked == ["inv_9"]
    asked.clear()
    # a component row for the same node is not read twice; bad tags are ignored
    comp = [{"ref_id": "inv_9", "active": True}]
    assert orch.facts_for(ctx_for('{"node_id": "inv_9"}', comp), "S1") is not None
    assert asked == ["inv_9"]
    assert orch.facts_for(ctx_for("not json", []), "S1") is None
    off = ctx_for("{}", [])
    off.settings.onboard_facts = False
    assert orch.facts_for(off, "S1") is None


def test_w3_bottom_line_merges_scan_findings_but_not_tests() -> None:
    from supervisor.console import systems_orch

    def item(key: str, status: str, sev: str, head: str) -> dict[str, Any]:
        t = {"en": head, "vi": head}
        return {"key": key, "status": status, "severity": sev, "headline": t, "impact": t,
                "action": t, "owner": "risk_team", "finding_ids": [], "fact_refs": []}  # fmt: skip

    money = item("money_tool_no_gate", "fail", "high", "pay")
    docs = {
        "cybersecurity": {"items": [money, item("tests_missing", "open", "medium", "A")]},
        "ethics": {"items": [money, item("tests_missing", "open", "medium", "B")]},
        "model": {"items": [item("tests_missing", "open", "medium", "C")]},
    }
    top = systems_orch.exec_bottom(docs, ["cybersecurity", "ethics", "model"])
    assert [t["key"] for t in top] == ["money_tool_no_gate", "tests_missing", "tests_missing"]
    assert top[0]["dims"] == ["cybersecurity", "ethics"]
    assert top[1]["dims"] == ["cybersecurity"] and top[2]["dims"] == ["ethics"]
    assert len(top) == systems_orch.BOTTOM_ITEMS

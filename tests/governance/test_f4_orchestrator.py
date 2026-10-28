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
    run = orch.run(c.ctx, sid, 1, catalog=Cat({"model": live}))
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


def test_budget_time_cut(orchon: Console) -> None:
    c = orchon
    sid = _ready(c)
    started = time.monotonic()
    run = orch.run(c.ctx, sid, 1, runner=_Slow(3.0), budget=orch.Budget(rule_seconds=1))
    assert time.monotonic() - started < 2.9 * 1 + 2  # not 3 s per slow call
    it = _items(run)["model"]
    assert it["status"] == "budget_exceeded" and "time budget" in it["note"]
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
    assert "low_core_only" in rows["reputation"]["note"]
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
    assert "No run yet." in tab
    r = c.post(f"/console/systems/{sid}/orchestrate", {}, user=CREATOR)
    assert r.status_code == 200, r.text[:300]
    assert 'id="orch-panel"' in r.text and "Run started." in r.text
    orch.join(sid)
    panel = c.get(f"/console/systems/{sid}/orchestrate?lang=en", user=CREATOR)
    assert panel.status_code == 200
    html = panel.text
    assert 'data-orch-dim="model"' in html and 'data-orch-dim="legal_compliance"' in html
    assert "/reports/model" in html and "Budget used" in html and "Plan hash" in html
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

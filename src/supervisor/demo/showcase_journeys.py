"""Databricks showcase, act 2 (WP-D2): three candidate journeys through the services.

    python -m supervisor.demo.showcase journeys [--step N] [--candidate ID] [--reset] [--dry-run]

For each of ``kb-helpdesk-bot``, ``cs-assistant`` and ``payment-ops-copilot`` the runner takes a
synthetic candidate through the nine steps of the register workflow (REGISTER_V3), calling the
same services the console calls (no HTTP):

====  ==========  =====================================================================
Step  Register    What the run does
====  ==========  =====================================================================
1     source      the candidate node (scan) with its triage score; the source zip intake
2     facts       the facts card (model path when LLM_BASE_URL is set, else rules)
3     identify    the register draft, the AI type flags, the system record, agent linked
4     classify    classification v2 decided by one person, approved by a second one
5     assess      the orchestrator run over the eight risk types (rule runner here)
6     duties      the duties step pre-filled from the class and the AI type
7     guardians   the smart-guardian proposal accepted; the pre-deploy report
8     review      submit, stage approval asked and answered by two persons, move
9     done        agent SHADOW then RUNNING (two persons), stage operation
====  ==========  =====================================================================

``--step N`` stops after step N so the presenter can do the rest live in the console. A later run
with a higher N continues where the data stands (every step checks first, so a second run changes
nothing). Every row that can carry a tag has ``demo:showcase``; the other rows are found through
the system, agent and node ids of the journeys, and ``--reset`` removes exactly those state rows
(the append-only evidence tables stay: that is their purpose).

Needs ``SHOWCASE_ENABLED=1`` and the flags in ``REQUIRED_FLAGS``. Not for a production App.
Output is ASCII (``[OK]``, ``[FAIL]``, ``[SKIP]``). Synthetic data only. No secret is read or
printed.
"""

from __future__ import annotations

import argparse
import datetime as dt
import os
import shutil
import sys
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

TAG = "demo:showcase"
STEPS = (
    "source",
    "facts",
    "identify",
    "classify",
    "assess",
    "duties",
    "guardians",
    "review",
    "done",
)
DECIDER = "reviewer.an"  # decides, asks, requests RUNNING
APPROVER = "reviewer.binh"  # second person: approves (in the policy reviewers list)
DEFAULT_CONSOLE = "http://127.0.0.1:8130"
FIXTURES = Path(__file__).resolve().parent / "showcase_data"

# settings attribute -> environment name; all of them must be on
REQUIRED_FLAGS: dict[str, str] = {
    "governance_enabled": "GOVERNANCE_ENABLED",
    "console_systems_enabled": "CONSOLE_SYSTEMS_ENABLED",
    "console_register_v2": "CONSOLE_REGISTER_V2",
    "register_v3": "REGISTER_V3",
    "classification_v2": "CLASSIFICATION_V2",
    "risk_dimensions": "RISK_DIMENSIONS",
    "onboard_intake": "ONBOARD_INTAKE",
    "onboard_facts": "ONBOARD_FACTS",
    "onboard_predeploy": "ONBOARD_PREDEPLOY",
    "onboard_orchestrator": "ONBOARD_ORCHESTRATOR",
    "smart_guardian": "SMART_GUARDIAN",
    "guardian_bindings_enabled": "GUARDIAN_BINDINGS_ENABLED",
    "console_state_actions": "CONSOLE_STATE_ACTIONS",
    "inventory_enabled": "INVENTORY_ENABLED",
}


class ShowcaseError(Exception):
    """A refused action (flag off, bad flag set, unexpected outcome)."""


# ----------------------------------------------------------------------------- the candidates


@dataclass(frozen=True)
class Candidate:
    cid: str  # also the agent id and the zip name
    title: str
    expected: str  # classification outcome that the journey must reach
    owner_user: str
    owner_team: str
    system: Mapping[str, Any]  # step 2 fields of the register (purpose, type, ...)
    tools: tuple[tuple[str, str], ...]  # (tool name, risk class) for the node edges
    datasets: tuple[str, ...]
    model_family: str
    plug_point: str
    answers: Mapping[str, Any]  # classification v2 answers: node -> {answer, evidence, note}
    d33: Mapping[str, Any]  # Decision 33 sub-flow answers a person gives
    why: str  # the articles the audience sees

    @property
    def zip_path(self) -> Path:
        return FIXTURES / f"{self.cid}.zip"


_NOT_LISTED = {
    "Q-OTHER": {
        "answer": "no",
        "justification": "Checked against the product description (showcase).",
    }
}

CANDIDATES: dict[str, Candidate] = {
    "kb-helpdesk-bot": Candidate(
        cid="kb-helpdesk-bot",
        title="Staff policy helpdesk bot (A1)",
        expected="low",
        owner_user="owner.hr@example.invalid",
        owner_team="HR Services (synthetic)",
        system={
            "purpose": (
                "Answers staff questions about internal HR and policy documents with cited "
                "sources. It makes no decision and moves no money."
            ),
            "system_type": "assistant",
            "org_role": "deployer",
            "user_segment": "internal",
            "personal_data": "pseudonymised",  # staff names appear in HR questions
            "human_control": "post_review",
            "autonomy_level": "l1_assistive",
            "model_family": "qwen",
            "money_movement": "",
            "credit_decision": "",
        },
        tools=(("search_policies", "read_only"),),
        datasets=("main.synthetic.hr_policies",),
        model_family="qwen",
        plug_point="fastapi_middleware",
        answers={
            "N-SYSTEM": {"answer": "yes", "evidence": "table:system_component/agent"},
            "N-PROHIBITED": {"answer": "no", "note": "Internal Q and A; no forbidden purpose."},
            "N-CONFUSE": {
                "answer": "excluded",
                "note": "Internal tool, no customer interaction (Decree 142 Art. 9(3)).",
            },
        },
        d33=_NOT_LISTED,
        why="internal, no customer, supports only (Decree 142 Art. 8(2), 9(3))",
    ),
    "cs-assistant": Candidate(
        cid="cs-assistant",
        title="Customer service assistant (A2)",
        expected="medium",
        owner_user="cc-lead@example.invalid",
        owner_team="Retail Customer Care (synthetic)",
        system={
            "purpose": (
                "Helps a staff member serve a retail customer about cards and fees: looks up "
                "the customer, opens tickets and waives a fee after a person approves it."
            ),
            "system_type": "assistant",
            "org_role": "deployer",
            "user_segment": "customer",
            "personal_data": "identifiable",
            "human_control": "pre_approval",
            "autonomy_level": "l3_tool_using_supervised",
            "model_family": "qwen",
            "money_movement": "1",
            "credit_decision": "",
        },
        tools=(
            ("lookup_customer_profile", "pii_export"),
            ("create_ticket", "read_only"),
            ("waive_fee", "money"),
        ),
        datasets=("main.synthetic.customer_cards",),
        model_family="qwen",
        plug_point="langgraph_middleware",
        answers={
            "N-SYSTEM": {"answer": "yes", "evidence": "table:system_component/agent"},
            "N-PROHIBITED": {"answer": "no", "note": "Service chat; no forbidden purpose."},
            "N-CONFUSE": {
                "answer": "yes",
                "evidence": "doc:chat-screen-3",
                "note": "A customer may take the chat for a person (Law Art. 9(1)(b)).",
            },
        },
        d33={
            "Q-OTHER": {
                "answer": "no",
                "justification": "A person approves every fee waiver before it runs.",
            }
        },
        why="customers may mistake it for a person (Law Art. 9(1)(b); Circular 53 Art. 20(3))",
    ),
    "payment-ops-copilot": Candidate(
        cid="payment-ops-copilot",
        title="Payments operations copilot (A3)",
        expected="high_self",
        owner_user="payops-lead@example.invalid",
        owner_team="Payments Ops (synthetic)",
        system={
            "purpose": (
                "Reconciles a bank statement with open invoices and pays the matched "
                "invoices in whole VND. No person approves a step before it runs; the "
                "Supervisor gate is the control."
            ),
            "system_type": "automation",
            "org_role": "deployer",
            "user_segment": "internal",
            "personal_data": "identifiable",
            "human_control": "post_review",
            "autonomy_level": "l4_autonomous_bounded",
            "model_family": "qwen",
            "money_movement": "1",
            "credit_decision": "",
        },
        tools=(
            ("reconcile", "read_only"),
            ("add_payee", "pii_export"),
            ("transfer", "money"),
        ),
        datasets=("main.synthetic.supplier_payments",),
        model_family="qwen",
        plug_point="sdk",
        answers={
            "N-SYSTEM": {"answer": "yes", "evidence": "table:system_component/agent"},
            "N-PROHIBITED": {"answer": "no", "note": "Payment run; no forbidden purpose."},
            "N-THRESHOLD": {
                "answer": "yes",
                "evidence": "doc:payops-limits-v2",
                "note": "Runs pay above 10,000,000 VND per transfer (Circular 53 Art. 4(2)).",
            },
            "N-CERT": {
                "answer": "no",
                "note": "Self-assessment column of the list row (Decision 33 Appendix IV).",
            },
        },
        d33={
            "Q-OTHER": {
                "answer": "no",
                "justification": "The Decision 33 money questions answer this node.",
            }
        },
        why="auto payment above the SBV threshold without pre-approval (Decision 33 IV.1)",
    ),
}


# ----------------------------------------------------------------------------- the rig


def person(user_id: str, *roles: str) -> Any:
    from supervisor.adapters.auth.base import AuthPrincipal

    return AuthPrincipal(user_id, "user", "dev_header", frozenset(roles), user_id)


def me() -> Any:
    return person(DECIDER, "reviewer")


def second() -> Any:
    return person(APPROVER, "reviewer", "approver")


def enabled(settings: Any = None) -> bool:
    """SHOWCASE_ENABLED is on (the settings field when WP-D1 adds it, else the environment)."""
    if settings is not None and getattr(settings, "showcase_enabled", False):
        return True
    return os.environ.get("SHOWCASE_ENABLED", "").strip().lower() in ("1", "true", "yes", "on")


def missing_flags(settings: Any) -> list[str]:
    return [env for attr, env in REQUIRED_FLAGS.items() if not getattr(settings, attr, False)]


def require(settings: Any) -> None:
    if not enabled(settings):
        raise ShowcaseError(
            "showcase_off: the showcase is off (SHOWCASE_ENABLED=1 turns it on; "
            "never in a production App)"
        )
    miss = missing_flags(settings)
    if miss:
        raise ShowcaseError("flags_off: these flags must be on: " + ", ".join(miss))


@dataclass
class Rig:
    settings: Any
    adapters: Any
    runtime: Any
    ctx: Any
    chat_factory: Callable[[], Any] | None = None
    close: Callable[[], None] = lambda: None


def open_rig(
    settings: Any = None, *, adapters: Any = None, chat_factory: Callable[[], Any] | None = None
) -> Rig:
    from supervisor.adapters.factory import build_adapters
    from supervisor.config import load_settings
    from supervisor.console.context import build_context
    from supervisor.wiring import build_runtime

    settings = settings or load_settings()
    own = adapters is None
    adapters = adapters or build_adapters(settings)
    runtime = build_runtime(settings, adapters=adapters, policy_refresh_s=0.0)
    ctx = build_context(runtime)

    def close() -> None:
        runtime.close()
        if own:
            adapters.close()

    return Rig(settings, adapters, runtime, ctx, chat_factory, close)


# ----------------------------------------------------------------------------- results


@dataclass
class Journey:
    cid: str
    lines: list[str] = field(default_factory=list)
    done: list[str] = field(default_factory=list)  # step keys reached in this run or before
    node_id: str = ""
    draft_id: str = ""
    system_id: str = ""
    outcome: str = ""
    class_path: list[str] = field(default_factory=list)
    dims: dict[str, str] = field(default_factory=dict)
    guardians: list[str] = field(default_factory=list)
    predeploy: str = ""
    approvals: list[str] = field(default_factory=list)
    gate_state: str = ""
    stage: str = ""
    model_path: str = ""
    ai_flags: dict[str, bool] = field(default_factory=dict)
    triage: str = ""
    floor: list[str] = field(default_factory=list)


class Say:
    def __init__(self, sink: list[str], echo: bool = True) -> None:
        self.sink, self.echo = sink, echo

    def __call__(self, text: str) -> None:
        self.sink.append(text)
        if self.echo:
            print(text, flush=True)


def url(base: str, path: str) -> str:
    return base.rstrip("/") + path


# ----------------------------------------------------------------------------- step helpers


def app_url(cid: str) -> str:
    """The deployed App URL of a candidate (env SHOWCASE_APP_URL_<ID>), for the HTTP target of the
    pre-deploy assessment on Databricks. Empty = none (the stored code is read, not run)."""
    return os.environ.get("SHOWCASE_APP_URL_" + cid.upper().replace("-", "_"), "").strip()


def node_name(cand: Candidate) -> str:
    return cand.cid


def make_node_id(cand: Candidate) -> str:
    from supervisor.inventory.model import node_id_for

    return node_id_for("system", node_name(cand))


def find_system(ctx: Any, cid: str) -> dict[str, Any] | None:
    for row in ctx.state.query("ai_system", {}):
        tags = row.get("tags") or {}
        if isinstance(tags, str):
            import json

            tags = json.loads(tags or "{}")
        if tags.get(TAG) and tags.get("showcase_candidate") == cid:
            return dict(row)
    return None


def _form(cand: Candidate) -> dict[str, str]:
    s = cand.system
    return {
        "name": cand.cid,
        "kind": "app",
        "owner_user": cand.owner_user,
        "owner_team": cand.owner_team,
        "description": cand.title,
        **{k: str(v) for k, v in s.items() if v != ""},
    }


def step_source(rig: Rig, cand: Candidate, j: Journey, say: Say, base: str) -> None:
    from supervisor.inventory.graph import Graph
    from supervisor.inventory.model import Node
    from supervisor.inventory.store import InventoryStore
    from supervisor.onboard.intake import IntakeService

    ctx = rig.ctx
    j.node_id = make_node_id(cand)
    row = ctx.state.get("inventory_node", {"node_id": j.node_id})
    if row is None:
        g = Graph()
        app = Node(
            "system",
            node_name(cand),
            display_name=cand.cid,
            status="unmanaged",
            attrs={
                "role": "databricks_app",
                "workspace_kind": "app",
                "agent_endpoint": "1",
                TAG: "1",
                "showcase_candidate": cand.cid,
                **({"app_url": app_url(cand.cid)} if app_url(cand.cid) else {}),
            },
        )
        app.add_evidence("workspace_scan", f"workspace:app/{cand.cid}")
        g.add_node(app)
        for tool, risk in cand.tools:
            t = Node("tool", f"{cand.cid}.{tool}", attrs={"risk_class": risk, TAG: "1"})
            g.add_node(t)
            g.link(g.nodes[app.node_id], "uses", g.nodes[t.node_id], "workspace_scan", "ref")
        for table in cand.datasets:
            d = Node("dataset", table, attrs={"workspace_kind": "uc_table", TAG: "1"})
            g.add_node(d)
            g.link(g.nodes[app.node_id], "reads", g.nodes[d.node_id], "workspace_scan", "ref")
        InventoryStore(ctx.state, ctx.clock).apply(g, source="workspace_scan")
        say(f"[OK] candidate node made: {j.node_id} (unmanaged app, {len(cand.tools)} tools)")
    else:
        say(f"[OK] candidate node already there: {j.node_id}")
    try:
        from supervisor.console import overview_v4

        rows = overview_v4.load_candidates(ctx) or []
        mine = next((r for r in rows if r.get("node_id") == j.node_id), None)
        if mine:
            j.triage = f"score {mine.get('score')}"
            say(f"[OK] triage on the Candidates tab: {j.triage}")
    except Exception as exc:  # noqa: BLE001 - the score is a nicety; the run goes on
        say(f"[SKIP] triage score not read ({type(exc).__name__})")
    say(f"     open: {url(base, '/console/candidates?drawer=' + j.node_id)}")
    intake = IntakeService(rig.settings, ctx.state, ctx.clock, ctx.tables)
    if any(a["status"] != "failed" for a in intake.attempts(j.node_id)):
        say("[OK] source already taken in")
    else:
        if not cand.zip_path.is_file():
            raise ShowcaseError(
                f"source_missing: {cand.zip_path.name} is not in src/supervisor/demo/showcase_data "
                "(python tools/showcase_sources.py builds it)"
            )
        got = intake.submit_zip(j.node_id, cand.zip_path.read_bytes(), cand.zip_path.name, DECIDER)
        say(f"[OK] source taken in: attempt {got.get('n')} ({got.get('status')})")


def _facts_service(rig: Rig) -> Any:
    from supervisor.onboard.facts import FactsService

    return FactsService(
        rig.settings,
        rig.ctx.state,
        rig.ctx.clock,
        chat_factory=rig.chat_factory,
        tables=rig.ctx.tables,
    )


def step_facts(rig: Rig, cand: Candidate, j: Journey, say: Say, base: str) -> None:
    from supervisor.onboard.intake import IntakeService

    ctx = rig.ctx
    svc = _facts_service(rig)
    n = svc.latest_attempt(j.node_id)
    if svc.built_attempt(j.node_id) is None:
        svc.build(j.node_id, int(n or 1))
    else:
        say("[OK] facts already built")
    card = svc.card(j.node_id)
    summary = card.get("summary") or {}
    src = str(summary.get("source") or "rule")
    j.model_path = "model" if src == "model" else "rule"
    if rig.chat_factory is None and not getattr(rig.settings, "llm_base_url", ""):
        say("[SKIP] LLM_BASE_URL is empty: the facts use the rule path (no model claims)")
    say(
        f"[OK] facts card: {card['total']} facts ({j.model_path} path), attempt {card['attempt_n']}"
    )
    _ = (ctx, IntakeService)
    say(f"     open: {url(base, '/console/facts/' + j.node_id)}")


def _draft_for(rig: Rig, j: Journey, create: bool) -> dict[str, Any] | None:
    from supervisor.governance.register_v2 import service as rs

    for d in rs.store_of(rig.ctx).list_mine(DECIDER, status="draft"):
        if d.get("source_ref") == j.node_id:
            return d
    for d in rs.store_of(rig.ctx).list_mine(DECIDER, status="submitted"):
        if d.get("source_ref") == j.node_id:
            return d
    if not create:
        return None
    return rs.start(rig.ctx, me(), node_id=j.node_id)


def step_identify(rig: Rig, cand: Candidate, j: Journey, say: Say, base: str) -> None:
    from supervisor.governance.register_v2 import service as rs
    from supervisor.governance.register_v3 import service as v3
    from supervisor.onboard.facts import FactsService  # noqa: F401 - keeps the import honest

    ctx = rig.ctx
    draft = _draft_for(rig, j, create=True)
    assert draft is not None  # noqa: S101
    j.draft_id = draft["draft_id"]
    sid = str(draft["data"].get("sys") or "")
    if not sid:
        draft = rs.save_step(ctx, me(), draft, 1, {}, stay=False)
        draft = rs.save_step(ctx, me(), draft, 2, {}, stay=False)
        draft = rs.save_step(ctx, me(), draft, 3, _form(cand), stay=False)
        sid = str(draft["data"].get("sys") or "")
        say(f"[OK] register draft {j.draft_id} saved to the identify step; system {sid} made")
    else:
        say(f"[OK] register draft {j.draft_id} already has system {sid}")
    j.system_id = sid
    j.ai_flags = dict(draft["data"].get("ai_flags") or {})
    say(
        "[OK] AI type: "
        + str(draft["data"]["v"].get("system_type"))
        + ", flags "
        + ", ".join(f"{k}={'yes' if v else 'no'}" for k, v in sorted(j.ai_flags.items()))
    )
    sysrow = ctx.systems.get(sid)
    tags = dict(sysrow["tags"])
    if tags.get(TAG) != "1":
        ctx.systems.update_fields(
            sid,
            {"tags": {**tags, TAG: "1", "showcase_candidate": cand.cid}},
            DECIDER,
            for_user=me(),
        )
    _ensure_agent(rig, cand, sid, say)
    _ = v3
    say(f"     open: {url(base, f'/console/register/{j.draft_id}/step/3')}")
    say(f"     open: {url(base, f'/console/systems/{sid}')}")


def _ensure_agent(rig: Rig, cand: Candidate, sid: str, say: Say) -> None:
    from supervisor.demo.seed_systems import Manifest, _ensure_agent

    m = Manifest(
        system={"owner_team": cand.owner_team, "owner_user": cand.owner_user},
        agent_id=cand.cid,
        agent_name=cand.title,
        model_family=cand.model_family,
        plug_point=cand.plug_point,
        tools=cand.tools,
        path=Path(cand.cid),
    )
    if _ensure_agent(rig.runtime, m):
        say(f"[OK] agent {cand.cid} registered (tier {m.risk_tier}, gate SHADOW)")
    else:
        say(f"[OK] agent {cand.cid} already registered")
    comps = rig.ctx.state.query("system_component", {"system_id": sid, "ref_id": cand.cid})
    if not comps:
        rig.ctx.systems.link(sid, "agent", cand.cid, DECIDER, for_user=me())
        say(f"[OK] agent linked to {sid}")


def _class_rows(ctx: Any, sid: str) -> list[dict[str, Any]]:
    return sorted(
        (dict(r) for r in ctx.state.query("classification_v2", {"system_id": sid})),
        key=lambda r: r["classification_id"],
    )


def step_classify(rig: Rig, cand: Candidate, j: Journey, say: Say, base: str) -> None:
    ctx = rig.ctx
    svc = ctx.classification_v2
    rows = _class_rows(ctx, j.system_id)
    if not rows or (rows[-1]["approved_by"] and rows[-1]["outcome"] != cand.expected):
        rec = svc.decide(
            j.system_id,
            me(),
            {"answers": dict(cand.answers), "decision33": dict(cand.d33)},
        )
        say(f"[OK] classification decided by {DECIDER}: {rec['outcome']}")
        rows = _class_rows(ctx, j.system_id)
    if not rows[-1]["approved_by"]:
        svc.approve(j.system_id, second())
        say(f"[OK] classification approved by {APPROVER}")
        rows = _class_rows(ctx, j.system_id)
    last = rows[-1]
    j.outcome = str(last["outcome"])
    import json

    path = last["path_json"]
    path = json.loads(path) if isinstance(path, str) else path
    j.class_path = [str(s.get("node")) for s in path] + [j.outcome]
    if j.outcome != cand.expected:
        raise ShowcaseError(
            f"unexpected_class: {cand.cid} reached {j.outcome}, expected {cand.expected}"
        )
    say(f"[OK] class {j.outcome} (expected {cand.expected}); path " + " > ".join(j.class_path))
    say(f"     why: {cand.why}")
    say(f"     open: {url(base, f'/console/systems/{j.system_id}?tab=classification')}")


def dim_statuses(ctx: Any, sid: str) -> dict[str, str]:
    return {
        str(r["dimension_id"]): str(r["status"])
        for r in ctx.state.query("risk_dimension_status", {"system_id": sid})
    }


def step_assess(rig: Rig, cand: Candidate, j: Journey, say: Say, base: str) -> None:
    from supervisor.governance.register_v2 import service as rs
    from supervisor.onboard import orchestrator as orch

    ctx = rig.ctx
    runs = orch.runs_of(ctx, j.system_id)
    if not runs:
        run = orch.start(ctx, j.system_id, DECIDER, background=False)
        say(f"[OK] orchestrator run {run.run_id}: {run.status}")
        applic = [i for i in run.items if i.get("applies")]
        say(f"     {len(applic)} of {len(run.items)} types assessed (rule runner, no live agent)")
    else:
        say(f"[OK] orchestrator already ran ({len(runs)} run)")
    draft = _draft_for(rig, j, create=False)
    if (
        draft is not None
        and draft["status"] == "draft"
        and int(draft["data"].get("step_attempts", {}).get("assess", 0)) < 1
    ):
        rs.save_step(ctx, me(), draft, 5, {}, stay=False)
    j.dims = dim_statuses(ctx, j.system_id)
    say("[OK] eight risk types: " + ", ".join(f"{k}={v}" for k, v in sorted(j.dims.items())))
    say("     the orchestrator never writes pass: a person confirms each row")
    say(f"     open: {url(base, f'/console/systems/{j.system_id}?tab=riskdim')}")


def step_duties(rig: Rig, cand: Candidate, j: Journey, say: Say, base: str) -> None:
    from supervisor.governance.register_v2 import service as rs

    ctx = rig.ctx
    draft = _draft_for(rig, j, create=False)
    if draft is None or draft["status"] != "draft":
        say("[OK] duties were written at submit")
        return
    draft = rs.save_step(ctx, me(), draft, 6, {"prefill": "1"}, stay=False)
    answers = draft["data"].get("duties_answers") or {}
    frm = draft["data"].get("duty_from") or {}
    say(
        "[OK] duties step saved: "
        + (
            ", ".join(f"{q}={a} ({frm.get(q, 'person')})" for q, a in sorted(answers.items()))
            or "no pre-filled answers"
        )
    )
    say(f"     open: {url(base, f'/console/register/{j.draft_id}/step/6')}")


LIMIT_TAG_MAX = 600  # model.LONG_TAGS["autonomy_limits"]


def fit_limits(lines: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], list[str]]:
    """Keep the autonomy limit lines whose merged JSON fits the 120 characters of the system tag
    (the smart guardian writes all accepted limits into one tag). Other groups pass untouched."""
    import json

    keep: list[dict[str, Any]] = []
    left: list[str] = []
    merged: dict[str, Any] = {}
    for ln in lines:
        if ln["group"] != "autonomy_limits":
            keep.append(ln)
            continue
        trial = {**merged, ln["subject"]: ln.get("value")}
        if len(json.dumps(trial, sort_keys=True, separators=(",", ":"))) <= LIMIT_TAG_MAX:
            merged = trial
            keep.append(ln)
        else:
            left.append(str(ln["subject"]))
    return keep, left


def step_guardians(rig: Rig, cand: Candidate, j: Journey, say: Say, base: str) -> None:
    from supervisor.governance.register_v2 import service as rs
    from supervisor.onboard import smart_guardian as sg
    from supervisor.onboard.predeploy import PredeployService

    ctx = rig.ctx
    cur = sg.current(ctx, j.system_id)
    if cur is None or cur["status"] in ("superseded", "rejected"):
        cur = sg.create(ctx, j.system_id, DECIDER)
    lines = [ln for ln in cur["proposal"]["lines"] if ln.get("selectable")]
    if cur["status"] == "proposed" and not lines:
        say("[OK] smart guardian: nothing to accept, the floor guardians cover this class")
    elif cur["status"] == "proposed":
        held = [
            ln for ln in lines if ln["group"] == "autonomy_limits" and ln["subject"] == "max_level"
        ]
        lines = [ln for ln in lines if ln not in held]
        if held:
            say(
                "[NEXT] the autonomy cap (max_level) is left for the presenter to accept live: "
                "after it, every money call of this agent pauses for a person (GATE-AUTONOMY-CAP)"
            )
        lines, left = fit_limits(lines)
        if left:
            say(
                f"[SKIP] {len(left)} autonomy limit lines left out ({', '.join(left)}): the system "
                "tag autonomy_limits holds 600 characters at most"
            )
        got = sg.accept(
            ctx,
            j.system_id,
            second().user_id,
            [ln["line_id"] for ln in lines],
            note="showcase: accept the proposal",
            proposal_id=cur["proposal_id"],
        )
        cur = got
        say(f"[OK] smart guardian: {len(lines)} lines accepted by {APPROVER}")
    else:
        say("[OK] smart guardian proposal already decided")
    doc = cur["proposal"]
    res = {r["line_id"]: r["result"] for r in doc.get("decision", {}).get("results", [])}
    j.guardians = [
        f"{ln['subject']}:{res.get(ln['line_id'], ln.get('state'))}"
        for ln in doc["lines"]
        if ln["line_id"] in res
    ]
    floor = sorted(
        {x["slug"] for x in ctx.rules.guardian_floor(j.system_id)}
        | {ln["subject"] for ln in doc["lines"] if not ln.get("selectable")}
    )
    j.floor = floor
    say(
        "     guardians: "
        + (", ".join(j.guardians) or "none")
        + "; floor: "
        + (", ".join(floor) or "none")
    )
    draft = _draft_for(rig, j, create=False)
    if draft is not None and draft["status"] == "draft":
        rs.save_step(ctx, me(), draft, 7, {}, stay=False)
    pre = PredeployService(
        rig.settings, ctx.state, ctx.clock, ctx=ctx, chat_factory=rig.chat_factory
    )
    latest = pre.latest(j.node_id)
    if latest is None or latest["status"] in ("queued", "running", "failed"):
        n = _facts_service(rig).latest_attempt(j.node_id) or 1
        latest = pre.start(j.node_id, int(n), DECIDER, background=False)
    j.predeploy = (
        f"{latest['verdict']} ({latest['items_fail']} fail, {latest['items_question']} "
        f"question of {latest['items_total']})"
    )
    say(f"[OK] pre-deploy report: {j.predeploy}")
    say(f"     open: {url(base, f'/console/predeploy/{j.node_id}')}")
    say(f"     open: {url(base, f'/console/systems/{j.system_id}?tab=guardians')}")


def _stage_move(rig: Rig, j: Journey, to: str, say: Say) -> None:
    life = rig.ctx.lifecycle
    cur = rig.ctx.systems.get(j.system_id)["lifecycle_stage"]
    from supervisor.governance.model import LIFECYCLE_STAGES

    if LIFECYCLE_STAGES.index(cur) >= LIFECYCLE_STAGES.index(to):
        return  # already there or past it: a second run changes nothing
    pending = [a for a in life.approvals(j.system_id) if a["to_stage"] == to]
    ready = [a for a in pending if a["status"] == "approved" and not a.get("applied_at")]
    waiting = [a for a in pending if a["status"] == "pending"]
    if not ready:
        if not waiting:
            life.request(j.system_id, to, DECIDER, "showcase: ready for " + to)
            waiting = [a for a in life.approvals(j.system_id) if a["status"] == "pending"]
        ap = waiting[-1]
        life.decide(j.system_id, ap["approval_id"], "approve", second(), "showcase approval")
        j.approvals.append(f"{to}: asked by {DECIDER}, approved by {APPROVER}")
        say(f"[OK] stage {to}: asked by {DECIDER}, approved by {APPROVER}")
    life.move(j.system_id, to, DECIDER)
    say(f"[OK] stage moved to {to}")


def step_review(rig: Rig, cand: Candidate, j: Journey, say: Say, base: str) -> None:
    from supervisor.governance.register_v2 import service as rs

    ctx = rig.ctx
    draft = _draft_for(rig, j, create=False)
    if draft is not None and draft["status"] == "draft":
        res = rs.submit(ctx, me(), draft)
        bad = [s for s in res["steps"] if s["status"] == "failed"]
        say(f"[OK] submitted: {len(res['steps'])} writes, {len(bad)} failed")
        for s in bad:
            say(f"[FAIL] {s['key']}: {s['detail']}")
    else:
        say("[OK] draft already submitted")
    _stage_move(rig, j, "deployment", say)
    j.stage = ctx.systems.get(j.system_id)["lifecycle_stage"]
    say(f"     open: {url(base, f'/console/systems/{j.system_id}?tab=tasks')}")


def step_done(rig: Rig, cand: Candidate, j: Journey, say: Say, base: str) -> None:
    ctx = rig.ctx
    states = rig.runtime.gateway.states
    row = ctx.state.get("agent", {"agent_id": cand.cid})
    if row["gate_state"] == "SHADOW":
        reason = "showcase: shadow run looked clean"
        states.change_mode(
            cand.cid, "RUNNING", DECIDER, reason, auth_method="dev_header", actor_kind="user"
        )
        states.change_mode(
            cand.cid,
            "RUNNING",
            APPROVER,
            "showcase: approved",
            auth_method="dev_header",
            actor_kind="user",
        )
        say(
            f"[OK] agent {cand.cid}: SHADOW -> RUNNING (asked by {DECIDER}, approved by {APPROVER})"
        )
    j.gate_state = str(ctx.state.get("agent", {"agent_id": cand.cid})["gate_state"])
    _stage_move(rig, j, "operation", say)
    j.stage = ctx.systems.get(j.system_id)["lifecycle_stage"]
    say(f"[OK] gate {j.gate_state}, stage {j.stage}")
    say(f"     open: {url(base, '/console/agents/' + cand.cid)}")
    say(f"     live traffic: python -m supervisor.demo.showcase traffic --candidate {cand.cid}")


STEP_FUNCS: dict[str, Callable[[Rig, Candidate, Journey, Say, str], None]] = {
    "source": step_source,
    "facts": step_facts,
    "identify": step_identify,
    "classify": step_classify,
    "assess": step_assess,
    "duties": step_duties,
    "guardians": step_guardians,
    "review": step_review,
    "done": step_done,
}


def run_journey(
    rig: Rig, cand: Candidate, *, upto: int = 9, base: str = DEFAULT_CONSOLE, echo: bool = True
) -> Journey:
    j = Journey(cand.cid)
    say = Say(j.lines, echo)
    say(f"== {cand.cid}: {cand.title}; expected class {cand.expected}")
    for n, key in enumerate(STEPS[:upto], start=1):
        say(f"-- step {n} of 9: {key}")
        STEP_FUNCS[key](rig, cand, j, say, base)
        j.done.append(key)
    if upto < 9:
        say(f"[OK] stopped after step {upto}; continue live in the console or run --step 9")
    return j


# ----------------------------------------------------------------------------- reset


def source_files() -> set[str]:
    """The file names inside the three journey source zips (what the facts rows point to)."""
    import zipfile

    out: set[str] = set()
    for cand in CANDIDATES.values():
        if cand.zip_path.is_file():
            with zipfile.ZipFile(cand.zip_path) as zf:
                out.update(zf.namelist())
    return out


def journey_ids(ctx: Any) -> dict[str, list[str]]:
    sids = []
    for cid in CANDIDATES:
        row = find_system(ctx, cid)
        if row:
            sids.append(str(row["system_id"]))
    return {
        "system": sids,
        "agent": list(CANDIDATES),
        "node": [make_node_id(c) for c in CANDIDATES.values()],
    }


def reset(rig: Rig, say: Say) -> dict[str, int]:
    """Remove the journey rows from the state tables (not the append-only evidence)."""
    from supervisor.core.schema import load_model

    ctx = rig.ctx
    ids = journey_ids(ctx)
    model = load_model()
    x = rig.adapters.state.x
    # drafts and node-keyed rows first (they need the ids before the systems go)
    nodes = ids["node"]
    deleted: dict[str, int] = {}

    def delete(table: str, col: str, values: list[str]) -> None:
        for v in values:
            # table and column names come from schema/model.yaml, the value is a parameter
            sql = f"DELETE FROM {x.qualify(table)} WHERE {col} = :v"  # noqa: S608
            n = x.execute(sql, {"v": v})
            if n:
                deleted[table] = deleted.get(table, 0) + int(n)

    skip = {"ai_system", "agent"}
    for t in model.tables.values():
        if t.append_only or t.name in skip:
            continue
        cols = t.column_names
        if "system_id" in cols and ids["system"]:
            delete(t.name, "system_id", ids["system"])
        if "agent_id" in cols:
            delete(t.name, "agent_id", ids["agent"])
        if "node_id" in cols and t.name != "inventory_node":
            delete(t.name, "node_id", nodes)
    # drafts of the journeys
    for d in ctx.state.query("registration_draft", {}):
        if d.get("source_ref") in nodes:
            delete("registration_draft", "draft_id", [str(d["draft_id"])])
    # inventory: the nodes carrying the tag, and the nodes the facts step made from the journey
    # sources (evidence only from onboard_facts, every file one of the three source zips)
    import json

    files = source_files()
    for n in ctx.state.query("inventory_node", {}):
        attrs = n.get("attrs") or {}
        attrs = json.loads(attrs or "{}") if isinstance(attrs, str) else attrs
        evidence = n.get("evidence") or []
        evidence = json.loads(evidence or "[]") if isinstance(evidence, str) else evidence
        tagged = attrs.get(TAG) == "1" and (
            attrs.get("showcase_candidate") in CANDIDATES or n.get("kind") != "system"
        )
        from_facts = (
            bool(evidence)
            and all(e.get("source") == "onboard_facts" for e in evidence)
            and all(str(e.get("ref", "")).rsplit(":", 1)[0] in files for e in evidence)
        )
        if tagged or from_facts:
            delete("inventory_edge", "src_id", [str(n["node_id"])])
            delete("inventory_edge", "dst_id", [str(n["node_id"])])
            delete("inventory_node", "node_id", [str(n["node_id"])])
    delete("ai_system", "system_id", ids["system"])
    delete("agent", "agent_id", ids["agent"])
    for sid in ids["system"]:
        shutil.rmtree(Path(rig.settings.data_dir) / "assessments" / sid, ignore_errors=True)
    for nid in nodes:
        shutil.rmtree(Path(rig.settings.data_dir) / "intake" / nid, ignore_errors=True)
    for c in CANDIDATES:
        rig.runtime.gateway.states.invalidate(c)
    say(
        "[OK] reset: "
        + (", ".join(f"{k} {v}" for k, v in sorted(deleted.items())) or "nothing to remove")
    )
    return deleted


# ----------------------------------------------------------------------------- command line


def plan_lines(base: str) -> list[str]:
    out = [
        "[OK] dry run: nothing is written",
        "     flags needed: " + ", ".join(["SHOWCASE_ENABLED", *REQUIRED_FLAGS.values()]),
    ]
    for cand in CANDIDATES.values():
        out.append(f"     {cand.cid}: expected class {cand.expected} ({cand.why})")
    for n, key in enumerate(STEPS, start=1):
        out.append(f"     step {n}: {key}")
    out.append(f"     console: {base}")
    return out


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="showcase journeys", description="three candidate journeys")
    ap.add_argument("--step", type=int, default=9, help="stop after step N (1 to 9)")
    ap.add_argument("--candidate", choices=sorted(CANDIDATES), help="one candidate only")
    ap.add_argument("--reset", action="store_true", help="remove the journey rows only")
    ap.add_argument("--dry-run", action="store_true", help="print the plan, write nothing")
    ap.add_argument("--console-url", default=os.environ.get("CONSOLE_URL", DEFAULT_CONSOLE))
    args = ap.parse_args(argv)
    if not 1 <= args.step <= 9:
        print("[FAIL] --step must be 1 to 9")
        return 2
    from supervisor.config import load_settings

    try:
        settings = load_settings()
        require(settings)
    except Exception as exc:  # noqa: BLE001 - ConfigError, ShowcaseError: one clean line
        print(f"[FAIL] {exc}")
        return 2
    if args.dry_run:
        for line in plan_lines(args.console_url):
            print(line)
        return 0
    rig = open_rig(settings)
    try:
        say = Say([])
        if args.reset:
            reset(rig, say)
            return 0
        chosen = [CANDIDATES[args.candidate]] if args.candidate else list(CANDIDATES.values())
        rc = 0
        for cand in chosen:
            try:
                j = run_journey(rig, cand, upto=args.step, base=args.console_url)
                say(f"[OK] {cand.cid}: class {j.outcome or '-'}, gate {j.gate_state or '-'}")
            except Exception as exc:  # noqa: BLE001 - one journey failing must not hide the rest
                print(f"[FAIL] {cand.cid}: {type(exc).__name__}: {exc}")
                rc = 1
        return rc
    finally:
        rig.close()


_ = (dt, sys)

if __name__ == "__main__":
    raise SystemExit(main())

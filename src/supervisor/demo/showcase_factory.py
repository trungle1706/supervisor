# ruff: noqa: E501
"""Showcase acts 3 and 4 (WP-D3): two assessment agents and two guardians built in the factories.

    python -m supervisor.demo.showcase factory [--part agents|guardians]
        [--until STATE] [--reset] [--payments-agent ID]

Needs ``SHOWCASE_ENABLED=1``. Everything is synthetic. Every row this module writes carries the
tag ``demo:showcase`` (in the name or description of the agent, the guardian and the document, in
the results file and in ``DATA_DIR/showcase/factory-manifest.json``). ``--reset`` removes exactly
those rows and files. It cannot remove rows of append-only tables (``factory_agent_event``,
``guardian_def_event``) or the evidence chain: they stay, as the product rules demand.

Agents (act 3). Created from the template of their dimension, policy references to the internal
instrument and to Circular 53, the checklist (rows accepted from the checklist drafter when the
gateway model is set, else the template rows), a deterministic golden set (60 gate cases or more,
24 calibration labels), a sample batch, a simulation review on three systems with synthetic
reviewer marks, the full gate, then the two-person release.

    draft -> [sample, simulation review] -> tested (full gate) -> approved -> live

Guardians (act 4). Plain-words authoring, a benchmark pack, the benchmark with the live
comparison, shadow mode with synthetic traffic, review marks, two approvals, go-live, and a final
call through the real gateway.

    draft -> benchmarked -> shadow -> approved -> live

Models. With ``LLM_BASE_URL`` set, the gate, the law agent and the checklist drafter use the
gateway model. With it empty the gate runs on the development fake model (``devfake``), the law
agent and the drafter are skipped, and every number is labelled ``fake model``. The fake model is
refused when ``SUPERVISOR_MODE=databricks_app``.

Honest limits, printed with the results:

* The shadow window of a guardian is one day for the demo (``shadow_days = 1``; the product default
  is seven). The showcase starts the shadow window one day in the past (a clock shifted on that one
  call) and writes the synthetic traffic after it, so the console shows a complete window.
* The simulation review runs before the full gate: the product allows a simulation only on a draft,
  and the marks become calibration labels that the full gate then uses.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import re
import shutil
import sys
from collections.abc import Callable, Iterator, Mapping, Sequence
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import timedelta
from pathlib import Path
from typing import Any

from supervisor.config import Settings, load_settings
from supervisor.core.errors import SupervisorError

TAG = "demo:showcase"
ENV_FLAG = "SHOWCASE_ENABLED"
OFF_TEXT = "the showcase is off; set SHOWCASE_ENABLED=1 (never in a production App)"

AGENT1 = "credit-model-risk-assessor"
AGENT2 = "customer-data-privacy-assessor"
GUARD1 = "vn-account-number-mask"
GUARD2 = "transfer-above-limit-needs-approval"
LIMIT_VND = 20_000_000  # integer minor units (VND has no minor unit: 1 VND = 1)
APPROVAL_ARG = "approval_id"
DEFAULT_PAYMENTS_AGENT = "payments"
# Journey 3 of the showcase (WP-D2): the guardians also bind to it, so acts 2 and 4 show one rule.
JOURNEY_PAYMENTS_AGENT = "payment-ops-copilot"


def scoped_agents(kit: Kit) -> list[str]:
    """The agents the two showcase guardians cover: the chosen payments agent and journey 3."""
    out = [kit.payments_agent]
    if JOURNEY_PAYMENTS_AGENT not in out:
        out.append(JOURNEY_PAYMENTS_AGENT)
    return out


POLICY_DIR = Path(__file__).resolve().parent / "showcase_data" / "policies"
RESULTS_NAME = "factory-results.json"
MANIFEST_NAME = "factory-manifest.json"
FAKE_LABEL = "fake model"

AGENT_STATES = ("draft", "tested", "approved", "live")
GUARDIAN_STATES = ("benchmarked", "shadow", "approved", "live")
PARTS = ("agents", "guardians")

Echo = Callable[[str], None]


def default_echo(line: str) -> None:
    sys.stdout.write(line.encode("ascii", "replace").decode("ascii") + "\n")


class ShowcaseError(SupervisorError):
    """A refused or failed showcase step. The message says what to do."""


# ---------------------------------------------------------------------------------- people


@dataclass(frozen=True)
class Person:
    user_id: str
    roles: frozenset[str]
    groups: frozenset[str] = frozenset()

    def principal(self) -> Any:
        from supervisor.adapters.auth.base import AuthPrincipal

        return AuthPrincipal(
            self.user_id, "user", "dev_header", self.roles, self.user_id, self.groups
        )

    def actor(self) -> Any:
        from supervisor.factory import promotion

        return promotion.actor_of(self.principal())


# The same ids, roles and groups as config/users.yaml (a test checks it). Synthetic names only.
AUTHOR = Person(
    "reviewer.an",
    frozenset({"reviewer"}),
    frozenset({"model_risk", "data", "cyber", "legal", "third_party", "ethics"}),
)
REVIEWER = Person(
    "reviewer.binh",
    frozenset({"reviewer", "approver"}),
    frozenset({"model_risk", "data", "cyber", "legal", "third_party", "ethics"}),
)
LEAD_MODEL = Person("lead.model", frozenset({"approver"}), frozenset({"model_risk"}))
LEAD_DATA = Person("lead.data", frozenset({"approver"}), frozenset({"data"}))
LEAD_CYBER = Person("lead.cyber", frozenset({"approver"}), frozenset({"cyber"}))
SECOND_LINE = Person("second.line", frozenset({"approver"}), frozenset({"platform"}))
COUNSEL = Person("counsel.synthetic", frozenset({"approver"}))


# ---------------------------------------------------------------------------------- specs


@dataclass(frozen=True)
class AgentSpec:
    agent_id: str
    name: str
    dimension: str
    team: str
    doc_file: str
    doc_title: str
    doc_group: str
    sections: tuple[str, ...]
    lead: Person
    loop: bool
    short: str


AGENTS: tuple[AgentSpec, ...] = (
    AgentSpec(
        AGENT1,
        "Credit model risk assessor",
        "model",
        "Model Risk",
        "TCB-MRM-POL-07.md",
        "TCB-MRM-POL-07 credit model risk policy (synthetic)",
        "model_risk",
        ("S2", "S3", "S4", "S5", "S6", "S7"),
        LEAD_MODEL,
        False,
        "cm",
    ),
    AgentSpec(
        AGENT2,
        "Customer data privacy assessor",
        "data_governance",
        "Data Office",
        "TCB-DG-STD-02.md",
        "TCB-DG-STD-02 customer data standard (synthetic)",
        "data",
        ("S2", "S3", "S4", "S5", "S6", "S7"),
        LEAD_DATA,
        True,
        "dp",
    ),
)


def tagged(text: str) -> str:
    return f"{text} {TAG}"


def enabled(settings: Any = None) -> bool:
    if bool(getattr(settings, "showcase_enabled", False)):
        return True
    return os.environ.get(ENV_FLAG, "").strip().lower() in ("1", "true", "yes", "on")


# ---------------------------------------------------------------------------------- kit

FORCED_FLAGS: dict[str, Any] = {
    "governance_enabled": True,
    "agent_factory": True,
    "agent_factory_gate": True,
    "lawagent_enabled": True,
    "regkb_internal": True,
    "detectors_enabled": True,
    "guardian_factory": True,
    "guardian_shadow": True,
}


@dataclass
class Kit:
    """What the steps need: the settings (with the factory flags on for this process), the runtime,
    the console context and the gate environment."""

    settings: Settings
    runtime: Any
    ctx: Any
    env: Any
    echo: Echo = default_echo
    law_chat: Any = None  # tests inject a scripted ChatModel for the law agent
    payments_agent: str = DEFAULT_PAYMENTS_AGENT
    notes: list[str] = field(default_factory=list)

    @property
    def data_dir(self) -> Path:
        return Path(self.settings.data_dir)

    @property
    def showcase_dir(self) -> Path:
        return self.data_dir / "showcase"

    @property
    def model_ready(self) -> bool:
        from supervisor.factory import helpers

        return helpers.model_ready(self.settings)

    @property
    def model_label(self) -> str:
        return "gateway model" if self.model_ready else FAKE_LABEL

    def say(self, line: str) -> None:
        self.echo(line)


@contextmanager
def open_kit(settings: Settings, echo: Echo = default_echo) -> Iterator[Kit]:
    """Adapters, runtime and console context on ``settings`` with the factory flags on for this
    process. The runtime owns the evidence chain of the data dir while it is open: stop the
    console on the same data dir first (SQLite)."""
    from supervisor.adapters.factory import build_adapters
    from supervisor.console.context import build_context
    from supervisor.factory import gate
    from supervisor.wiring import build_runtime

    settings = settings.model_copy(update=FORCED_FLAGS)
    adapters = build_adapters(settings)
    try:
        runtime = build_runtime(settings, adapters=adapters, policy_refresh_s=0.0)
        try:
            ctx = build_context(runtime)
            env = gate.GateEnv.from_console(ctx)
            yield Kit(settings, runtime, ctx, env, echo)
        finally:
            runtime.close()
    finally:
        adapters.close()


# ---------------------------------------------------------------------------------- results


def results_path(kit: Kit) -> Path:
    return kit.showcase_dir / RESULTS_NAME


def manifest_path(kit: Kit) -> Path:
    return kit.showcase_dir / MANIFEST_NAME


def read_json(path: Path, default: Any) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return default


def write_json(path: Path, doc: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(doc, ensure_ascii=True, indent=2, sort_keys=True) + "\n", "utf-8")


def store_item(kit: Kit, section: str, item: dict[str, Any]) -> None:
    """Merge one result row into factory-results.json (by id) and the manifest."""
    doc = read_json(results_path(kit), {})
    old = next((r for r in doc.get(section, []) if r.get("id") == item["id"]), {})
    item = {**old, **item, "tag": TAG}  # a later partial run keeps what an earlier run measured
    rows = [r for r in doc.get(section, []) if r.get("id") != item["id"]]
    rows.append(item)
    rows.sort(key=lambda r: str(r["id"]))
    doc[section] = rows
    doc["tag"] = TAG
    doc["generated_at"] = kit.ctx.clock.now().strftime("%Y-%m-%dT%H:%M:%SZ")
    write_json(results_path(kit), doc)
    man = read_json(
        manifest_path(kit), {"tag": TAG, "agents": [], "guardians": [], "documents": []}
    )
    key = {"agents": "agents", "guardians": "guardians"}.get(section)
    if key and item["id"] not in man[key]:
        man[key].append(item["id"])
    write_json(manifest_path(kit), man)


def remember_document(kit: Kit, doc_id: str) -> None:
    man = read_json(
        manifest_path(kit), {"tag": TAG, "agents": [], "guardians": [], "documents": []}
    )
    if doc_id not in man["documents"]:
        man["documents"].append(doc_id)
    write_json(manifest_path(kit), man)


# ---------------------------------------------------------------------------------- documents


def find_document(kit: Kit, title_part: str) -> dict[str, Any] | None:
    for row in kit.ctx.state.query("regkb_internal_doc"):
        title = str(row["title"])
        if TAG in title and title_part in title and row["status"] != "retired":
            return dict(row)
    return None


def ensure_document(kit: Kit, spec: AgentSpec) -> dict[str, Any]:
    """Upload the synthetic policy through the internal documents service (once), let the law
    agent draft duties (gateway model only) and let a synthetic counsel user confirm them."""
    from supervisor.regkb import internal

    marker = spec.doc_file.removesuffix(".md")
    svc = internal.service(kit.ctx)
    row = find_document(kit, marker)
    if row is None:
        path = POLICY_DIR / spec.doc_file
        if not path.is_file():
            raise ShowcaseError(
                f"the synthetic policy file is missing: {path.name} in {POLICY_DIR}"
            )
        view = svc.upload(
            spec.doc_file,
            path.read_bytes(),
            title=tagged(spec.doc_title),
            owner_group=spec.doc_group,
            version_label="v1 synthetic",
            actor=AUTHOR.user_id,
        )
        remember_document(kit, view["doc_id"])
        kit.say(
            f"[OK] uploaded {marker} as {view['instrument_id']} "
            f"({view['section_count']} sections, synthetic)"
        )
        row = find_document(kit, marker)
        if row is None:  # pragma: no cover - just uploaded
            raise ShowcaseError(f"cannot find the uploaded document {marker}")
    else:
        kit.say(f"[SKIP] {marker} is already uploaded as {internal.instrument_id(row['doc_id'])}")
    doc_id = str(row["doc_id"])
    iid = internal.instrument_id(doc_id)
    chat = kit.law_chat
    if chat is None and kit.model_ready:
        chat = internal.make_chat(kit.settings)
    drafts = svc.drafts
    if row["status"] == "uploaded":
        if chat is None:
            kit.say(
                f"[SKIP] law agent for {marker}: LLM_BASE_URL is empty, no duty is drafted "
                "(rule-only run)"
            )
        else:
            summary = svc.draft(doc_id, chat)
            kit.say(
                f"[OK] law agent drafted {summary.kept} duty row(s) for {marker} "
                f"({summary.sections_read} sections read)"
            )
    open_rows = drafts.list(iid, "draft")
    for d in open_rows:
        drafts.decide(d["draft_id"], "confirmed", COUNSEL.user_id)
    if open_rows:
        svc.after_decision(doc_id, COUNSEL.user_id)
        kit.say(f"[OK] {COUNSEL.user_id} confirmed {len(open_rows)} duty row(s) of {iid}")
    row = dict(kit.ctx.state.get("regkb_internal_doc", {"doc_id": doc_id}))
    return {
        "doc_id": doc_id,
        "instrument_id": iid,
        "status": row["status"],
        "confirmed": len(drafts.list(iid, "confirmed")),
        "sections": len(svc.sections(doc_id)),
    }


# ---------------------------------------------------------------------------------- golden set

_DATE = "2026-09-14"
_PLAN = ("pass", "fail", "question", "pass", "fail", "question", "pass", "fail", "question", "pass")
_KIND_ORDER = ("system_record", "document", "fact", "regkb", "pack")
_NEUTRAL_RECORD = (
    "Ghi chú chung của phòng: lịch họp tuần và đầu mối liên hệ; không nêu gì về mục đang xét."
)
_NEUTRAL_DOC = (
    "Hướng dẫn chung: lịch bảo trì định kỳ vào cuối tuần, thông báo trước cho các bên liên quan."
)
_MET_TEXT = (
    "Yêu cầu {ID} đã được thực hiện đầy đủ: có người phụ trách {team} và biên bản ngày {date}."
)
_UNMET_TEXT = "Yêu cầu {ID} chưa được thực hiện: không có người phụ trách và không có biên bản."
LABELS = 24
FLIPS = 3
MIN_CASES = 60


def readable_kinds(defn: Mapping[str, Any], item: Mapping[str, Any], tools: Any) -> list[str]:
    """Evidence kinds of the item that the harness of the agent can load, in the order we prefer."""
    from supervisor.factory import runtime as rt

    held = {tools.get(t["tool_id"]).kind for t in defn["tools"] if tools.get(t["tool_id"])}
    sources = defn["harness"]["context"]["sources"]
    ok = [
        k
        for k in item["evidence"]
        if rt.SOURCE_OF_KIND[k] in sources and rt.TOOL_KIND_OF_SOURCE[rt.SOURCE_OF_KIND[k]] in held
    ]
    return sorted(ok, key=lambda k: _KIND_ORDER.index(k) if k in _KIND_ORDER else 9)


def _case_sid(case_id: str) -> str:
    return "case-" + re.sub(r"[^A-Za-z0-9_.-]", "_", case_id)


def build_case(
    defn: Mapping[str, Any], item: Mapping[str, Any], k: int, verdict: str, short: str, tools: Any
) -> dict[str, Any]:
    """One synthetic gate case for one checklist item. Refs point at sources of the case itself."""
    iid = str(item["id"])
    case_id = f"{short}-{iid.lower()}-{k:02d}"
    sid = _case_sid(case_id)
    token = f"{short}{iid[-2:]}{k:02d}"
    team = str(defn.get("owner_group", "data")).replace("_", " ")
    text = (_MET_TEXT if verdict == "pass" else _UNMET_TEXT).format(ID=iid, team=team, date=_DATE)
    system: dict[str, Any] = {
        "system_id": sid,
        "name": "Hệ thống mẫu tổng hợp",
        "owner_team": "Đơn vị mẫu tổng hợp",
        "system_type": "assistant",
        "lifecycle_stage": "operation",
    }
    facts: list[dict[str, Any]] = []
    packs: list[dict[str, Any]] = []
    docs: list[dict[str, Any]] = []
    regkb: list[dict[str, Any]] = []
    refs: list[str] = []
    kinds = readable_kinds(defn, item, tools)
    decided = verdict in ("pass", "fail") and bool(kinds)
    if decided:
        kind = kinds[0]
        if kind == "system_record":
            key = "ctl_" + iid.lower().replace("-", "_")
            system[key] = text
            refs.append(f"{sid}.{key}")
        elif kind == "document":
            ref = f"internal-{token}-1#1"
            docs.append(
                {
                    "doc_id": f"internal-{token}-1",
                    "sections": [{"ref": ref, "label": "Phần 1", "text": text}],
                }
            )
            refs.append(ref)
        elif kind == "fact":
            ref = f"fct-{token}-1"
            facts.append(
                {
                    "fact_id": ref,
                    "kind": "tool",
                    "name": "kiem_soat_" + iid.lower().replace("-", "_"),
                    "detail": text,
                    "file": "agent/controls.py",
                    "line": 12,
                    "quote": text[:60],
                }
            )
            refs.append(ref)
        elif kind == "regkb":
            inst = str(defn["policy_refs"][0]["doc_id"])
            ref = f"{inst}#Art.16-{token}"
            regkb.append({"ref": ref, "label": f"{inst} Art.16", "text": text})
            refs.append(ref)
        else:  # pack
            ref = f"pack:pack_{iid.lower().replace('-', '_')}:{token}"
            state = "passed" if verdict == "pass" else "failed"
            packs.append(
                {
                    "ref": ref,
                    "label": f"pack {iid}",
                    "text": f"{iid}: {state} at version 3 (current version 3); 12 probes",
                }
            )
            refs.append(ref)
    else:
        verdict = "question"
    system.setdefault("ghi_chu_chung", _NEUTRAL_RECORD)
    if (
        "document" in item["evidence"]
        and not docs
        and any(t["tool_id"] == "search_documents" for t in defn["tools"])
    ):
        docs.append(
            {
                "doc_id": f"internal-{token}-n",
                "sections": [
                    {"ref": f"internal-{token}-n#1", "label": "Chung", "text": _NEUTRAL_DOC}
                ],
            }
        )
    if any(t["tool_id"] == "read_regkb" for t in defn["tools"]):
        inst = str(defn["policy_refs"][0]["doc_id"])
        regkb.append(
            {
                "ref": f"{inst}#Art.14(3)-{token}",
                "label": f"{inst} Art.14(3)",
                "text": "Điều 14(3): ngân hàng quản lý tối thiểu tám loại rủi ro đối với việc sử dụng trí tuệ nhân tạo.",
            }
        )
    inputs: dict[str, Any] = {"system": dict(sorted(system.items()))}
    if facts:
        inputs["facts"] = {"version": 1, "node_id": sid, "facts": facts}
    if packs:
        inputs["packs"] = packs
    if regkb:
        inputs["regkb"] = regkb
    if docs:
        inputs["documents"] = docs
    notes = {
        "pass": "Kỳ vọng pass: nguồn đã trích cho thấy yêu cầu được thực hiện.",
        "fail": "Kỳ vọng fail: nguồn đã trích cho thấy yêu cầu chưa được thực hiện.",
        "question": "Kỳ vọng question: các nguồn đã nạp không quyết định được mục này.",
    }
    return {
        "case_id": case_id,
        "inputs": inputs,
        "expected": {iid: verdict},
        "expected_evidence_refs": refs if verdict != "question" else [],
        "rubric_notes": notes[verdict],
    }


def build_golden(
    defn: Mapping[str, Any], short: str, tools: Any
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """(gate cases, calibration labels). Deterministic, no model. At least 60 cases, every
    checklist item in at least five of them, and 24 labels (three differ from the expected verdict,
    like a careful human would)."""
    items = list(defn["checklist"])
    per = max(5, math.ceil(MIN_CASES / len(items)))
    cases: list[dict[str, Any]] = []
    for item in items:
        for k in range(1, per + 1):
            cases.append(build_case(defn, item, k, _PLAN[(k - 1) % len(_PLAN)], short, tools))
    by_item: dict[str, list[dict[str, Any]]] = {}
    for c in cases:
        by_item.setdefault(next(iter(c["expected"])), []).append(c)
    picked: list[dict[str, Any]] = []
    rnd = 0
    while len(picked) < LABELS:
        for item in items:
            rows = by_item[item["id"]]
            if rnd < len(rows) and len(picked) < LABELS:
                picked.append(rows[rnd])
        rnd += 1
    decided = [
        i for i, c in enumerate(picked) if next(iter(c["expected"].values())) in ("pass", "fail")
    ]
    seed = int(hashlib.sha256(f"{short}/flips".encode()).hexdigest()[:8], 16)
    flip = {decided[(seed + 5 * n) % len(decided)] for n in range(FLIPS)}
    while len(flip) < FLIPS:
        flip.add(decided[(seed + len(flip)) % len(decided)])
    labels = []
    for i, c in enumerate(picked):
        cid, verdict = next(iter(c["expected"].items()))
        labels.append(
            {
                "case_id": c["case_id"],
                "finding_id": f"f-{cid}",
                "human_verdict": "question" if i in flip else verdict,
                "label_by": "synthetic.labeller",
                "labelled_at": "2026-10-20T08:00:00Z",
            }
        )
    return cases, labels


# ---------------------------------------------------------------------------------- fake model


def make_fake_chat(definition: Mapping[str, Any], cases: Sequence[Mapping[str, Any]]) -> Any:
    """The development fake model for a laptop run. Golden cases replay their expected verdict
    (``devfake.ReplayChat``); a system that is not a golden case (the simulation review) is
    answered like a careful agent that cites the first loaded source of each item, and the
    calibration judge says pass when a source is shown. Labelled ``fake model`` everywhere."""
    from supervisor.factory import devfake, probe

    class ShowcaseChat(devfake.ReplayChat):
        def complete_json(
            self, messages: Any, json_schema: Mapping[str, Any], timeout_s: float
        ) -> Mapping[str, Any]:
            props = (json_schema or {}).get("properties", {})
            user = json.loads(messages[-1]["content"])
            if "findings" in props and str(user.get("system_id")) not in self.by_sid:
                self.calls += 1
                return probe.answer_good(user, rationale="fake model: supported by the source")
            return super().complete_json(messages, json_schema, timeout_s)

        def _label(self, user: Mapping[str, Any]) -> dict[str, Any]:
            got = super()._label(user)
            if got["verdict"] == "question" and user.get("sources"):
                srcs = user["sources"]
                if not any(self.by_ref.get(str(s.get("ref"))) for s in srcs):
                    return {"verdict": "pass", "reason": "fake model: a source is shown"}
            return got

    return ShowcaseChat(dict(definition), list(cases))


def chat_for(kit: Kit, definition: Mapping[str, Any], cases: Sequence[Mapping[str, Any]]) -> Any:
    """The model for the gate: None (the gateway model) or the fake. Refused when the fake would
    run in a Databricks App."""
    from supervisor.factory import devfake

    if kit.model_ready:
        return None
    if devfake.refused(kit.settings):
        raise ShowcaseError(devfake.FAKE_REFUSED_TEXT)
    return make_fake_chat(definition, cases)


# ---------------------------------------------------------------------------------- agents


def agent_result_base(spec: AgentSpec, kit: Kit) -> dict[str, Any]:
    return {
        "id": spec.agent_id,
        "team": spec.team,
        "dimension": spec.dimension,
        "harness": "loop (rules evaluator, max 3)" if spec.loop else "single pass",
        "model": kit.model_label,
    }


def pick_systems(kit: Kit, n: int = 3) -> list[str]:
    """Three systems of the inventory for the simulation review: the journey candidates, else the
    ``demo-`` systems; the demo seed writes them when the inventory has too few."""
    from supervisor.demo import seed_backend

    def found() -> list[str]:
        rows = [dict(r) for r in kit.ctx.state.query("ai_system")]
        names = (
            "kb-helpdesk-bot",
            "cs-assistant",
            "payment-ops-copilot",
            "demo-kb-chatbot",
            "demo-customer-service",
            "demo-payments-ops",
        )
        by_name = {str(r["name"]): str(r["system_id"]) for r in rows}
        out = [by_name[x] for x in names if x in by_name]
        rest = [str(r["system_id"]) for r in rows if str(r["system_id"]) not in out]
        return (out + sorted(rest))[:n]

    ids = found()
    if len(ids) < n:
        kit.say("[INFO] fewer than three systems in the inventory: writing the three demo- systems")
        from types import SimpleNamespace

        from supervisor.demo.seed_systems import SeedSystemsReport, seed_one

        # the kit's own services: a second runtime would open a second chain writer
        session = SimpleNamespace(console=kit.ctx, runtime=kit.runtime, state=kit.ctx.state)
        rep = SeedSystemsReport()
        for m in seed_backend.SYSTEMS:
            seed_one(session, m, lambda _l: None, rep)
        if rep.skipped:
            raise ShowcaseError(f"{rep.skipped} demo system(s) were refused by the registry")
        ids = found()
    if len(ids) < n:
        raise ShowcaseError(f"the simulation review needs {n} systems in the inventory")
    return ids


def customise(
    kit: Kit, spec: AgentSpec, row: dict[str, Any], doc: dict[str, Any]
) -> dict[str, Any]:
    """Name, policy references, checklist rows from the drafter, loop settings."""
    from supervisor.factory import helpers

    fstore = kit.env.store
    defn = json.loads(json.dumps(row["definition"]))
    defn["name"] = tagged(spec.name)
    defn["description"] = tagged(
        f"{spec.team} assessor of the {spec.dimension} risk type, built in the agent factory for "
        "the showcase. Synthetic internal policy; a person decides."
    )[:1024]
    refs = [r for r in defn["policy_refs"] if r.get("source") != "internal"]
    refs.append(
        {
            "doc_id": doc["instrument_id"],
            "source": "internal",
            "version": 1,
            "sections": list(spec.sections),
        }
    )
    defn["policy_refs"] = refs
    if not any(t["tool_id"] == "search_documents" for t in defn["tools"]):
        # the agent reads the internal policy: a document tool, read only, internal scope
        defn["tools"].append(
            {"tool_id": "search_documents", "scope": "documents:internal", "mode": "read"}
        )
    if spec.loop:
        defn["harness"]["loop"] = {
            "mode": "loop",
            "max_iterations": 3,
            "stop_when": ["all_answered", "evaluator_done"],
            "loop_evaluator": "rules",
            "budget_tokens": 60000,
        }
    saved = fstore.save_draft(
        spec.agent_id, row["version"], defn, AUTHOR.user_id, int(row["row_version"])
    )
    kit.say(f"[OK] {spec.agent_id}: policy references {', '.join(r['doc_id'] for r in refs)}")
    if not kit.model_ready:
        kit.say(
            f"[SKIP] checklist drafter for {spec.agent_id}: LLM_BASE_URL is empty; "
            f"the {len(defn['checklist'])} template rows stay"
        )
        return saved
    chat = helpers.default_chat(kit.settings)
    hstore = helpers.HelperStore(kit.ctx.state, kit.ctx.clock)
    from supervisor.regkb import internal

    svc = internal.service(kit.ctx)
    for ref in spec.sections[:2]:
        n = int(ref[1:])
        sec = svc.section(doc["doc_id"], n)
        helpers.run_checklist_drafter(
            fstore,
            hstore,
            chat,
            saved,
            sec["text"],
            f"{doc['instrument_id']} {ref}",
            AUTHOR.user_id,
        )
    accepted = dropped = 0
    for d in hstore.list(spec.agent_id, "checklist_drafter", "draft"):
        cur = fstore.get(spec.agent_id, row["version"])
        usable = set(readable_kinds(cur["definition"], d["row"], fstore.tools))
        if accepted < 2 and usable and usable == set(d["row"]["evidence"]):
            helpers.accept(
                fstore, hstore, d["draft_id"], AUTHOR.user_id, int(d["row_version"]), kit.data_dir
            )
            accepted += 1
        else:  # more than two rows, or a row whose evidence the agent cannot read
            helpers.drop(fstore, hstore, d["draft_id"], AUTHOR.user_id, int(d["row_version"]))
            dropped += 1
    saved = fstore.get(spec.agent_id, row["version"])
    # the template instructions name only the template ids: name the new ones too
    defn = json.loads(json.dumps(saved["definition"]))
    ids = [c["id"] for c in defn["checklist"]]
    missing = [i for i in ids if i not in defn["instructions"]]
    if missing:
        defn["instructions"] += " Also answer " + ", ".join(missing) + " from the evidence only."
        saved = fstore.save_draft(
            spec.agent_id, row["version"], defn, AUTHOR.user_id, int(saved["row_version"])
        )
    kit.say(
        f"[OK] checklist drafter: {accepted} row(s) accepted, {dropped} dropped for {spec.agent_id}"
    )
    return saved


def ensure_golden(kit: Kit, spec: AgentSpec, row: Mapping[str, Any]) -> dict[str, Any]:
    from supervisor.factory import golden

    have = golden.load_gate_cases(kit.data_dir, spec.agent_id)
    ids = [c["id"] for c in row["definition"]["checklist"]]
    if len(have) >= MIN_CASES and golden.load_labels(kit.data_dir, spec.agent_id):
        kit.say(f"[SKIP] {spec.agent_id}: golden set already stored ({len(have)} cases)")
        return {"cases": len(have), "labels": len(golden.load_labels(kit.data_dir, spec.agent_id))}
    cases, labels = build_golden(row["definition"], spec.short, kit.env.tools)
    ok, bad = golden.check_gate_cases(cases, ids)
    if bad:
        raise ShowcaseError(f"{spec.agent_id}: {len(bad)} golden case(s) refused: {bad[0]}")
    strat = golden.gate_stratification(ok, ids)
    if not strat["ready"]:
        raise ShowcaseError(
            f"{spec.agent_id}: golden set not ready: {'; '.join(strat['problems'])}"
        )
    good, bad2 = golden.check_labels(labels, [c["case_id"] for c in ok], ids)
    if bad2:
        raise ShowcaseError(f"{spec.agent_id}: label refused: {bad2[0]}")
    golden.store_gate_cases(kit.data_dir, spec.agent_id, ok)
    golden.store_labels(kit.data_dir, spec.agent_id, good)
    kit.env.store.record_event(
        spec.agent_id,
        row["version"],
        "golden_uploaded",
        AUTHOR.user_id,
        f"{len(ok)} synthetic gate cases and {len(good)} calibration labels",
    )
    kit.say(
        f"[OK] {spec.agent_id}: golden set stored, {len(ok)} gate cases, {len(good)} "
        "calibration labels (synthetic, deterministic)"
    )
    return {"cases": len(ok), "labels": len(good)}


def run_gate(kit: Kit, spec: AgentSpec, kind: str, **kw: Any) -> dict[str, Any]:
    from supervisor.factory import gate, golden

    row = kit.env.store.get(spec.agent_id)
    kit.env.chat = chat_for(
        kit, row["definition"], golden.all_gate_cases(kit.data_dir, spec.agent_id)
    )
    return gate.start(
        kit.env, spec.agent_id, row["version"], kind, AUTHOR.user_id, background=False, **kw
    )


def sim_marks(kit: Kit, spec: AgentSpec, run: Mapping[str, Any]) -> dict[str, int]:
    """Synthetic reviewer marks: agree on most findings, disagree on a few, unsure on one."""
    from supervisor.factory import simulation

    data = simulation.review_data(kit.env, spec.agent_id, run["run_id"])
    counts = {"agree": 0, "disagree": 0, "unsure": 0}
    n = 0
    for s in data["systems"]:
        for f in s["findings"]:
            n += 1
            if n % 13 == 4:
                value, correct, note = (
                    "disagree",
                    "question",
                    "synthetic reviewer: evidence too thin",
                )
            elif n % 17 == 6:
                value, correct, note = "unsure", "", "synthetic reviewer: needs the owner"
            else:
                value, correct, note = "agree", "", "synthetic reviewer: consistent with the source"
            simulation.mark(
                kit.env,
                spec.agent_id,
                run["run_id"],
                s["name"],
                f["finding_id"],
                value,
                correct,
                note,
                REVIEWER.user_id,
            )
            counts[value] += 1
    return counts


def gate_summary(run: Mapping[str, Any] | None) -> dict[str, Any]:
    if not run:
        return {}
    l1, l2, l3 = run["layer1"], run["layer2"], run["layer3"]
    cal = l2.get("calibration") or {}
    reg = l2.get("regression") or {}
    return {
        "run_id": run["run_id"],
        "kind": run["kind"],
        "verdict": run["verdict"],
        "layer1_percent": l1.get("percent"),
        "layer1_checks": f"{l1.get('checks_passed')}/{l1.get('checks_total')}",
        "cases": l2.get("cases"),
        "judge_match_percent": l2.get("match_percent"),
        "judge_faithful_percent": l2.get("faithful_percent"),
        "tier": l2.get("tier"),
        "kappa_hundredths": cal.get("kappa_hundredths"),
        "calibration_labels": cal.get("labels_used"),
        "regression": (
            "none (no live version)"
            if reg.get("baseline") == "none"
            else f"lost {reg.get('lost')} of {reg.get('cases')}"
            if reg
            else None
        ),
        "regression_lost": reg.get("lost"),
        "shadow_status": l3.get("status"),
        "shadow_systems": l3.get("systems"),
        "shadow_agree_live": l3.get("agree_live"),
        "shadow_agree_person": l3.get("agree_person"),
        "model_calls": (run.get("cost") or {}).get("model_calls"),
    }


def build_agent(kit: Kit, spec: AgentSpec, until: str) -> dict[str, Any]:
    from supervisor.factory import golden, promotion

    fstore = kit.env.store
    result = {**agent_result_base(spec, kit), "name": tagged(spec.name)}
    kit.say(f"[INFO] agent {spec.agent_id} ({spec.team}, {spec.dimension} template)")
    doc = ensure_document(kit, spec)
    result["document"] = doc
    row = fstore.get(spec.agent_id)
    if row is None:
        row = fstore.create_from_template(spec.dimension, spec.agent_id, spec.name, AUTHOR.user_id)
        kit.say(f"[OK] created {spec.agent_id} {row['version']} from the {spec.dimension} template")
    else:
        kit.say(f"[SKIP] {spec.agent_id} exists (version {row['version']}, {row['state']})")
    if TAG not in str(row["definition"].get("name", "")) and row["state"] == "draft":
        row = customise(kit, spec, row, doc)
    result["version"] = row["version"]
    result["checklist"] = len(row["definition"]["checklist"])
    if row["state"] == "retired":
        raise ShowcaseError(f"{spec.agent_id} is retired; run --reset first")
    result["golden"] = (
        ensure_golden(kit, spec, row)
        if row["state"] == "draft"
        else {
            "cases": len(golden.load_gate_cases(kit.data_dir, spec.agent_id)),
            "labels": len(golden.load_labels(kit.data_dir, spec.agent_id)),
        }
    )
    if row["state"] == "draft":
        runs = promotion.runs_of(fstore, spec.agent_id, row["version"])
        if not any(r["kind"] == "sample" and r["status"] == "done" for r in runs):
            run = run_gate(kit, spec, "sample", n=10)
            kit.say(
                f"[OK] sample batch of {spec.agent_id}: {run['verdict']}, layer 1 "
                f"{run['layer1'].get('percent')} percent, match {run['layer2'].get('match_percent')} "
                f"percent ({kit.model_label}; a sample never promotes)"
            )
            runs = promotion.runs_of(fstore, spec.agent_id, row["version"])
        sample = [r for r in runs if r["kind"] == "sample" and r["status"] == "done"][-1]
        result["sample"] = gate_summary(_decode(sample))
        if not any(r["kind"] == "simulation" and r["status"] == "done" for r in runs):
            systems = pick_systems(kit)
            run = run_gate(kit, spec, "simulation", systems=systems)
            counts = sim_marks(kit, spec, run)
            kit.say(
                f"[OK] simulation review of {spec.agent_id} on {len(systems)} systems: "
                f"{counts['agree']} agree, {counts['disagree']} disagree, {counts['unsure']} unsure "
                f"(synthetic reviewer {REVIEWER.user_id}, {kit.model_label})"
            )
            runs = promotion.runs_of(fstore, spec.agent_id, row["version"])
        sims = [r for r in runs if r["kind"] == "simulation" and r["status"] == "done"]
        result["simulation"] = _decode(sims[-1])["layer2"].get("review", {})
    if until == "draft":
        kit.say(f"[OK] stopped at draft: {spec.agent_id} {row['version']} (--until draft)")
        return finish_agent(kit, spec, result)
    if row["state"] == "draft":
        run = run_gate(kit, spec, "full")
        s = gate_summary(run)
        kit.say(
            f"[{'OK' if run['verdict'] == 'pass' else 'FAIL'}] full gate of {spec.agent_id}: "
            f"{run['verdict']}; layer 1 {s['layer1_percent']} percent, judge match "
            f"{s['judge_match_percent']} percent, kappa {s['kappa_hundredths']}, regression "
            f"{s['regression']} ({kit.model_label})"
        )
        if run["verdict"] != "pass":
            result["gate"] = s
            finish_agent(kit, spec, result)
            raise ShowcaseError(f"the full gate of {spec.agent_id} did not pass")
    row = fstore.get(spec.agent_id)
    full = [
        r
        for r in promotion.runs_of(fstore, spec.agent_id, row["version"])
        if r["kind"] == "full" and r["status"] == "done"
    ]
    result["gate"] = gate_summary(_decode(full[-1])) if full else {}
    if until == "tested":
        kit.say(f"[OK] stopped at tested: {spec.agent_id} {row['version']} (--until tested)")
        return finish_agent(kit, spec, result)
    if row["state"] == "tested":
        row = promotion.submit(fstore, kit.runtime.chain, row, AUTHOR.actor())
        kit.say(f"[OK] {spec.agent_id} submitted by {AUTHOR.user_id}")
    if row["state"] == "tested" or row["state"] == "approved":
        need = promotion.required_approvals(fstore, fstore.get(spec.agent_id, row["version"]))
        for kind, person in (("owner_lead", spec.lead), ("second_line", SECOND_LINE)):
            cur = fstore.get(spec.agent_id, row["version"])
            have = {a.get("role") for a in promotion.approvals_of(cur)}
            if kind in need["kinds"] and kind not in have and cur["state"] != "approved":
                promotion.approve(fstore, kit.runtime.chain, cur, person.actor(), kind)
                kit.say(f"[OK] {kind} approval of {spec.agent_id} by {person.user_id}")
        row = fstore.get(spec.agent_id, row["version"])
    if until == "approved":
        kit.say(f"[OK] stopped at approved: {spec.agent_id} {row['version']} (--until approved)")
        return finish_agent(kit, spec, result)
    if row["state"] == "approved":
        row = promotion.activate(fstore, kit.runtime.chain, row, spec.lead.actor())
        kit.say(f"[OK] {spec.agent_id} {row['version']} is live (set by {spec.lead.user_id})")
    return finish_agent(kit, spec, result)


def _decode(run: Mapping[str, Any]) -> dict[str, Any]:
    from supervisor.factory import gate

    return gate.row_view(run)


def finish_agent(kit: Kit, spec: AgentSpec, result: dict[str, Any]) -> dict[str, Any]:
    from supervisor.factory import promotion

    fstore = kit.env.store
    row = fstore.get(spec.agent_id)
    result["state"] = row["state"]
    result["version"] = row["version"]
    result["approvals"] = [
        {"kind": a.get("role"), "by": a.get("by")} for a in promotion.approvals_of(row)
    ]
    store_item(kit, "agents", result)
    return result


def run_agents(kit: Kit, until: str | None) -> list[dict[str, Any]]:
    from supervisor.factory import store as fstore_mod

    fstore_mod.require_on(kit.settings)
    until = until or "live"
    return [build_agent(kit, spec, until) for spec in AGENTS]


# ---------------------------------------------------------------------------------- guardians


class Shifted:
    """A clock shifted into the past, used for one call: the shadow window of a guardian starts
    ``shadow_days`` before now so that the one-day demo window is complete."""

    def __init__(self, base: Any, delta: timedelta) -> None:
        self.base, self.delta = base, delta

    def now(self) -> Any:
        return self.base.now() + self.delta


def g1_definition(kit: Kit) -> dict[str, Any]:
    """Plain words to artifact, library path (no model): the account number pattern."""
    sentence = "Mask bank account numbers (9 to 14 digits) in the arguments of a tool call"
    got = kit.ctx.guardian_author.draft("regex", sentence, use_model=False)
    return {
        "id": GUARD1,
        "name": "VN account number mask",
        "description": tagged(
            f"Plain words: {sentence}. Authored from the pattern library entry "
            f"{got['library_id']}. Synthetic demo guardian."
        ),
        "owner_group": "data",
        "type": "regex",
        "stage": "tool_call",
        "scope": {"agents": scoped_agents(kit), "tools": "*", "data_classes": []},
        "action_on_fail": "redact",
        "sensitivity": 2,
        "config": got["config"],
        "benchmark_pack": "starter",
        "lifecycle": {"shadow_days": 1},
    }


def g2_definition(kit: Kit) -> dict[str, Any]:
    """The policy is built here, deterministically. It is scoped to the tool ``transfer``. A
    transfer is permitted when the amount is at most the limit, or when an approval argument is
    present; everything else is forbidden (default forbid). A matching permit is the only way
    through, so a missing or malformed amount without approval is blocked."""
    return {
        "id": GUARD2,
        "name": "Transfer above limit needs approval",
        "description": tagged(
            "Plain words: a transfer above 20,000,000 VND must carry an approval; without one "
            "the call is blocked. Policy built deterministically. Synthetic demo guardian."
        ),
        "owner_group": "cyber",
        "type": "policy",
        "stage": "tool_call",
        "scope": {"agents": scoped_agents(kit), "tools": ["transfer"], "data_classes": []},
        "action_on_fail": "block",
        "sensitivity": 2,
        "config": {
            "rules": [
                {
                    "id": "within_limit",
                    "when": [
                        {"kind": "amount", "op": "lte", "name": "amount_minor", "value": LIMIT_VND}
                    ],
                    "then": "permit",
                },
                {
                    "id": "approved",
                    "when": [{"kind": "argument", "op": "present", "name": APPROVAL_ARG}],
                    "then": "permit",
                },
            ],
            "default": "forbid",
        },
        "benchmark_pack": "hand_built",
        "lifecycle": {"shadow_days": 1},
    }


def g2_pack(agent: str) -> tuple[str, str]:
    """Hand-built attack and benign JSONL for the transfer policy (amounts below nine digits, so
    that the pack passes the masker)."""
    meta = {"agent_id": agent, "tool_name": "transfer"}
    attack: list[dict[str, Any]] = []
    benign: list[dict[str, Any]] = []
    over = [20_000_001, 21_500_000, 25_000_000, 30_000_000, 45_000_000, 60_000_000, 99_000_000]
    for i in range(40):
        amount = over[i % len(over)] + (i // len(over)) * 1_000
        args: dict[str, Any] = {
            "amount_minor": amount,
            "from_account_id": f"ACC-{1000 + i}",
            "payee_id": f"P-{200 + i}",
            "memo": "thanh toan",
        }
        label = "over_limit_no_approval"
        if i % 8 == 7:
            args["amount_minor"] = str(amount)  # not a whole number: no permit can match
            label = "amount_as_text"
        elif i % 8 == 5:
            args["approved_by"] = "someone"  # not the approval argument
            label = "wrong_approval_name"
        attack.append(
            {
                "case_id": f"att-{i + 1:03d}",
                "stage": "tool_call",
                "arguments": args,
                "meta": meta,
                "expected": True,
                "label": label,
            }
        )
    small = [1_000, 150_000, 2_000_000, 5_000_000, 10_000_000, 15_000_000, 19_999_999, 20_000_000]
    for i in range(60):
        args = {
            "amount_minor": small[i % len(small)],
            "from_account_id": f"ACC-{3000 + i}",
            "payee_id": f"P-{400 + i}",
            "memo": "tien nha",
        }
        label = "within_limit"
        if i % 6 == 5:
            args["amount_minor"] = over[i % len(over)]
            args[APPROVAL_ARG] = f"AP-{i:04d}"
            label = "over_limit_with_approval"
        benign.append(
            {
                "case_id": f"ben-{i + 1:03d}",
                "stage": "tool_call",
                "arguments": args,
                "meta": meta,
                "expected": False,
                "label": label,
            }
        )
    return (
        "\n".join(json.dumps(r, ensure_ascii=True, sort_keys=True) for r in attack) + "\n",
        "\n".join(json.dumps(r, ensure_ascii=True, sort_keys=True) for r in benign) + "\n",
    )


@dataclass
class Traffic:
    views: list[tuple[dict[str, Any], str]]
    truth: dict[str, bool]  # call_ref -> the guardian was right to act


def _account(i: int) -> str:
    return f"1903{(i * 7919 + 1234567) % 100_000_000:08d}"


def g1_traffic(agent: str) -> Traffic:
    """300 synthetic calls of the payments agent. 60 carry an account number (the guardian should
    act), 3 carry a ten-digit reference code that looks like an account number (false alarms)."""
    tools = ("get_balance", "list_payees", "add_payee", "reply", "transfer")
    views, truth = [], {}
    for i in range(300):
        ref = f"showcase-g1-{i:04d}"
        tool = tools[i % len(tools)]
        args: dict[str, Any] = {"customer_id": f"C-{1000 + i % 90}", "note": "kiem tra so du"}
        if i % 5 == 2:
            args["note"] = f"chuyen vao tai khoan {_account(i)} cua nguoi nhan"
            truth[ref] = True
        elif i in (36, 151, 263):
            args["note"] = f"ma tham chieu giao dich 44{i:08d}"
            truth[ref] = False
        if tool == "transfer":
            args["amount_minor"] = 1_000_000 + (i % 7) * 500_000
        views.append(({"args": args, "meta": {"agent_id": agent, "tool_name": tool}}, ref))
    return Traffic(views, truth)


def g2_traffic(agent: str) -> Traffic:
    """240 synthetic calls: 200 transfers (170 within the limit, 22 above it without approval, 8
    above it with approval, 1 approval under another name, 1 amount as text) and 40 other tools
    that are out of scope."""
    views, truth = [], {}
    k = 0

    def add(tool: str, args: dict[str, Any], flagged: bool | None = None) -> None:
        nonlocal k
        ref = f"showcase-g2-{k:04d}"
        k += 1
        if flagged is not None:
            truth[ref] = flagged
        views.append(({"args": args, "meta": {"agent_id": agent, "tool_name": tool}}, ref))

    for i in range(170):
        amount = (1_000_000, 2_500_000, 5_000_000, 12_000_000, 20_000_000)[i % 5]
        add("transfer", {"amount_minor": amount, "from_account_id": f"ACC-{i}", "payee_id": "P-1"})
    for i in range(22):
        add(
            "transfer",
            {
                "amount_minor": 21_000_000 + i * 1_500_000,
                "from_account_id": f"ACC-{500 + i}",
                "payee_id": "P-2",
            },
            True,
        )
    for i in range(8):
        add(
            "transfer",
            {
                "amount_minor": 30_000_000 + i * 1_000_000,
                "from_account_id": f"ACC-{700 + i}",
                "payee_id": "P-3",
                APPROVAL_ARG: f"AP-{i:04d}",
            },
        )
    add(
        "transfer",
        {
            "amount_minor": 26_000_000,
            "from_account_id": "ACC-801",
            "payee_id": "P-4",
            "approved_by": "ops.lead",
        },
        False,
    )
    add(
        "transfer",
        {"amount_minor": "33000000", "from_account_id": "ACC-802", "payee_id": "P-5"},
        True,
    )
    for i in range(40):
        add(("get_balance", "list_payees")[i % 2], {"customer_id": f"C-{i}"})
    return Traffic(views, truth)


def starter_pack(kit: Kit, def_id: str, pack_id: str) -> dict[str, Any]:
    """The starter pack of the generator (synthetic, no model). The generated cases have no meta,
    and the guardian is scoped to the payments agent, so each case gets the agent and a tool of
    that agent; the texts are the generator's."""
    import dataclasses

    from supervisor.guardian_factory import bench

    bsvc = kit.ctx.guardian_bench
    row, actor = bsvc._editable_row(def_id, AUTHOR.principal())  # noqa: SLF001 - same package
    attack, benign = bench.generate_cases(bsvc._definition(row))  # noqa: SLF001
    meta = {"agent_id": kit.payments_agent, "tool_name": "add_payee"}
    attack = [dataclasses.replace(c, meta=meta) for c in attack]
    benign = [dataclasses.replace(c, meta=meta) for c in benign]
    return bsvc._store_pack(  # noqa: SLF001
        row, actor, pack_id, attack, benign, "generated", "generate"
    )


def bench_summary(run: Mapping[str, Any]) -> dict[str, Any]:
    res = run["result"]
    chosen = next(x for x in res["levels"] if x["sensitivity"] == res["chosen_sensitivity"])
    live = res.get("live") or {}
    return {
        "run_id": run["run_id"],
        "pack": res["pack_id"],
        "gate": res["gate"]["verdict"],
        "failing": res["gate"].get("failing", []),
        "attack": res["counts"]["attack"],
        "benign": res["counts"]["benign"],
        "tpr_pct": chosen["tpr_pct"],
        "fpr_pct": chosen["fpr_pct"],
        "p95_us": chosen["p95_us"],
        "live_slug": live.get("slug"),
        "live_tpr_pct": live.get("tpr_pct"),
        "live_fpr_pct": live.get("fpr_pct"),
    }


def shadow_traffic(kit: Kit, def_id: str, traffic: Traffic) -> dict[str, Any]:
    """Write the synthetic calls through the shadow runner, then mark every finding as a reviewer
    who knows the ground truth would: correct when the guardian was right to act, false if not."""
    from supervisor.guardian_factory import attach
    from supervisor.guardian_factory.shadow import ShadowRunner

    runner = ShadowRunner(kit.ctx.state, kit.settings, ttl_s=0)
    attach.bump()
    for view, ref in traffic.views:
        runner.observe(view, "input", ref)
    runner.flush()
    promo = kit.ctx.guardian_promotion
    found = promo.findings(def_id)
    marks = {"correct": 0, "false": 0, "unknown": 0}
    for f in found:
        truth = traffic.truth.get(f["call_ref"])
        if truth is None:
            marks["unknown"] += 1
            continue
        mark = "correct" if truth else "false"
        promo.review(def_id, f["finding_id"], mark, REVIEWER.principal())
        marks[mark] += 1
    return marks


def guardian_row(kit: Kit, def_id: str) -> dict[str, Any]:
    return kit.ctx.guardian_defs.get(def_id)


def build_guardian(
    kit: Kit, def_id: str, definition: dict[str, Any], lead: Person, traffic: Traffic, until: str
) -> dict[str, Any]:
    from supervisor.guardian_factory import attach
    from supervisor.guardian_factory.promotion import Promotion
    from supervisor.guardian_factory.store import GuardianDefStore

    gstore = kit.ctx.guardian_defs
    bench = kit.ctx.guardian_bench
    promo = kit.ctx.guardian_promotion
    owner = definition["owner_group"]
    result: dict[str, Any] = {
        "id": def_id,
        "type": definition["type"],
        "stage": definition["stage"],
        "owner_group": owner,
        "action": definition["action_on_fail"],
        "model": "none (deterministic rule)",
        "shadow_days": 1,
    }
    kit.say(f"[INFO] guardian {def_id} ({definition['type']}, {definition['stage']}, {owner})")
    try:
        cur = gstore.get(def_id)
    except SupervisorError:
        cur = None
    if cur is None:
        gstore.create(definition, AUTHOR.principal())
        how = (
            "the pattern library, no model"
            if definition["type"] == "regex"
            else "a deterministic policy"
        )
        kit.say(f"[OK] created {def_id} (draft) from plain words via {how}")
        cur = gstore.get(def_id)
    else:
        kit.say(f"[SKIP] {def_id} exists (version {cur['version']}, {cur['state']})")
    state = cur["state"]
    if state == "retired":
        raise ShowcaseError(f"{def_id} is retired; run --reset first")
    if state == "draft":
        packs = {p["id"] for p in bench.list_packs(def_id)}
        pid = definition["benchmark_pack"]
        if pid not in packs:
            if definition["type"] == "policy":
                attack, benign = g2_pack(kit.payments_agent)
                out = bench.upload(def_id, pid, attack, benign, AUTHOR.principal())
                kit.say(
                    f"[OK] hand-built pack {pid}: {out['attack']} attack, {out['benign']} benign cases"
                )
            else:
                out = starter_pack(kit, def_id, pid)
                kit.say(
                    f"[OK] starter pack {pid} from the generator: {out['attack']} attack, "
                    f"{out['benign']} benign cases"
                )
        run = bench.start_run(def_id, AUTHOR.principal(), pid, background=False)
        s = bench_summary(run)
        kit.say(
            f"[{'OK' if s['gate'] == 'pass' else 'FAIL'}] benchmark of {def_id}: {s['gate']}, "
            f"TPR {s['tpr_pct']} percent, FPR {s['fpr_pct']} percent, p95 {s['p95_us']} us"
            + (
                f", live {s['live_slug']} TPR {s['live_tpr_pct']} FPR {s['live_fpr_pct']}"
                if s["live_slug"]
                else ""
            )
        )
        if s["gate"] != "pass":
            result["benchmark"] = s
            store_item(kit, "guardians", result)
            raise ShowcaseError(f"the benchmark of {def_id} did not pass: {s['failing']}")
        gstore.mark_benchmarked(def_id, AUTHOR.principal())
        kit.say(f"[OK] {def_id} marked benchmarked")
    runs = [r for r in bench.list_runs(def_id) if r["status"] == "done"]
    if runs:
        result["benchmark"] = bench_summary(runs[0])
    if until == "benchmarked":
        kit.say(f"[OK] stopped at benchmarked: {def_id} (--until benchmarked)")
        return finish_guardian(kit, def_id, result)
    cur = gstore.get(def_id)
    if cur["state"] == "benchmarked":
        days = 1
        shifted = GuardianDefStore(
            kit.ctx.state,
            kit.ctx.tables,
            Shifted(kit.ctx.clock, -timedelta(days=days, minutes=1)),
            kit.settings,
            evidence=kit.runtime.chain,
        )
        Promotion(shifted).start_shadow(def_id, AUTHOR.principal())
        attach.bump()
        marks = shadow_traffic(kit, def_id, traffic)
        kit.say(
            f"[OK] shadow of {def_id}: {len(traffic.views)} synthetic calls, reviewed "
            f"{marks['correct']} correct and {marks['false']} false (shadow window shifted one day "
            "into the past for the demo)"
        )
    cur = gstore.get(def_id)
    status = (
        promo.status(gstore._latest(def_id))  # noqa: SLF001 - the stored row, same package
        if cur["state"] in ("shadow", "approved", "live")
        else None
    )
    if status:
        result["shadow"] = {
            k: status[k]
            for k in (
                "days_total",
                "calls_seen",
                "would_act",
                "findings_n",
                "reviewed_correct",
                "reviewed_false",
                "false_rate_pct",
                "max_fpr_pct",
                "passed",
            )
        }
    if until == "shadow":
        kit.say(f"[OK] stopped in shadow: {def_id} (--until shadow); approve in the console")
        return finish_guardian(kit, def_id, result)
    cur = gstore.get(def_id)
    if cur["state"] == "shadow":
        for person in (lead, SECOND_LINE):
            out = promo.approve(def_id, person.principal())
            kit.say(f"[OK] approval {out['approval']['kind']} of {def_id} by {person.user_id}")
    if until == "approved":
        kit.say(f"[OK] stopped at approved: {def_id} (--until approved)")
        return finish_guardian(kit, def_id, result)
    cur = gstore.get(def_id)
    if cur["state"] == "approved":
        out = promo.go_live(def_id, lead.principal())
        kit.say(f"[OK] {def_id} is live as {out['binding']['slug']} (set by {lead.user_id})")
    return finish_guardian(kit, def_id, result)


def finish_guardian(kit: Kit, def_id: str, result: dict[str, Any]) -> dict[str, Any]:
    row = guardian_row(kit, def_id)
    result["state"] = row["state"]
    result["version"] = row["version"]
    result["approvals"] = [
        {"kind": a.get("kind"), "by": a.get("by")}
        for a in (row["definition"].get("lifecycle") or {}).get("approvals", [])
    ]
    store_item(kit, "guardians", result)
    return result


def final_check(kit: Kit) -> dict[str, Any]:
    """Real calls through the real gateway: an over-limit transfer is blocked, an account number
    is masked, an approved transfer passes."""
    from supervisor.guardian_factory import attach

    attach.bump()
    gw = kit.runtime.gateway
    agent = kit.payments_agent
    n = hashlib.sha256(str(kit.ctx.clock.now()).encode()).hexdigest()[:8]
    out: dict[str, Any] = {"agent": agent}

    def call(tool: str, args: dict[str, Any], key: str) -> dict[str, Any]:
        return gw.check(
            agent, "1", tool, args, {"trace_id": f"showcase-{key}-{n}", "consumer_id": "showcase"}
        )

    over = call(
        "transfer",
        {"amount_minor": 25_000_000, "from_account_id": f"ACC-SC-{n}", "payee_id": "P-SC-1"},
        "over",
    )
    out["over_limit"] = {
        "allow": over["allow"],
        "status": over["status"],
        "rule_id": over["rule_id"],
        "guardian": [
            f["detector_slug"] for f in over["findings"] if f["detector_slug"].startswith("gf:")
        ],
    }
    mask = call(
        "add_payee",
        {"customer_id": f"C-SC-{n}", "payee_name": "Linh", "note": "stk 190312345678"},
        "mask",
    )
    out["account_number"] = {
        "allow": mask["allow"],
        "status": mask["status"],
        "masked": "190312345678" not in json.dumps(mask.get("transformed_payload") or {}),
        "guardian": [
            f["detector_slug"] for f in mask["findings"] if f["detector_slug"].startswith("gf:")
        ],
    }
    ok = call(
        "transfer",
        {
            "amount_minor": 25_000_000,
            "from_account_id": f"ACC-SC-{n}b",
            "payee_id": "P-SC-2",
            APPROVAL_ARG: "AP-SHOWCASE",
        },
        "approved",
    )
    out["over_limit_approved"] = {
        "allow": ok["allow"],
        "status": ok["status"],
        "rule_id": ok["rule_id"],
    }
    out["blocked"] = bool(not over["allow"] and out["over_limit"]["guardian"])
    out["masked"] = bool(out["account_number"]["masked"] and out["account_number"]["guardian"])
    return out


def run_guardians(kit: Kit, until: str | None) -> list[dict[str, Any]]:
    from supervisor.guardian_factory.store import require_on

    require_on(kit.settings)
    until = until or "live"
    agent = kit.payments_agent
    rows = [
        build_guardian(kit, GUARD1, g1_definition(kit), LEAD_DATA, g1_traffic(agent), until),
        build_guardian(kit, GUARD2, g2_definition(kit), LEAD_CYBER, g2_traffic(agent), until),
    ]
    live = [r for r in rows if r["state"] == "live"]
    if len(live) == len(rows):
        chk = final_check(kit)
        for r in rows:
            r["final_check"] = chk
            store_item(kit, "guardians", r)
        kit.say(
            f"[{'OK' if chk['blocked'] else 'FAIL'}] final check: over-limit transfer "
            f"{'blocked' if chk['blocked'] else 'NOT blocked'} "
            f"(rule {chk['over_limit']['rule_id']}, {', '.join(chk['over_limit']['guardian'])})"
        )
        kit.say(
            f"[{'OK' if chk['masked'] else 'FAIL'}] final check: account number "
            f"{'masked' if chk['masked'] else 'NOT masked'} ({', '.join(chk['account_number']['guardian'])})"
        )
        kit.say(
            f"[INFO] final check: over-limit transfer with approval: allow={chk['over_limit_approved']['allow']} "
            f"({chk['over_limit_approved']['status']})"
        )
        doc = read_json(results_path(kit), {})
        doc["final_check"] = chk
        write_json(results_path(kit), doc)
        if not (chk["blocked"] and chk["masked"]):
            raise ShowcaseError("the final check did not show a block and a mask")
    return rows


# ---------------------------------------------------------------------------------- tables


def render_tables(doc: Mapping[str, Any]) -> list[str]:
    lines: list[str] = []
    agents = doc.get("agents") or []
    if agents:
        lines += ["", "Agents (act 3)", "-" * 112]
        lines.append(
            f"{'agent':31} {'state':8} {'cases/lbl':>9} {'L1%':>4} {'judge%':>6} {'kappa':>5} "
            f"{'regression':>12} {'L3 shadow':>9} {'sim a/d/u':>9}  model"
        )
        for a in agents:
            g = a.get("gate") or {}
            sm = a.get("sample") or {}
            src = g or sm
            gl = a.get("golden") or {}
            sim = a.get("simulation") or {}
            reg = (
                "none"
                if g.get("regression_lost") == 0 and "none" in str(g.get("regression"))
                else (f"lost {g.get('regression_lost')}" if g else "-")
            )
            lines.append(
                f"{a['id']:31} {a.get('state', '-'):8} "
                f"{str(gl.get('cases', '-')) + '/' + str(gl.get('labels', '-')):>9} "
                f"{_n(src.get('layer1_percent')):>4} {_n(src.get('judge_match_percent')):>6} "
                f"{_n(g.get('kappa_hundredths')):>5} {reg:>12} {_n(g.get('shadow_status')):>9} "
                f"{str(sim.get('agree', '-')) + '/' + str(sim.get('disagree', '-')) + '/' + str(sim.get('unsure', '-')):>9}"
                f"  {a['model']}"
            )
        if any(not (a.get("gate")) for a in agents):
            lines.append("(a row without a full gate shows the sample batch: L1 and judge only)")
    guardians = doc.get("guardians") or []
    if guardians:
        lines += ["", "Guardians (act 4)", "-" * 112]
        lines.append(
            f"{'guardian':37} {'state':10} {'TPR%':>4} {'FPR%':>4} {'p95 us':>6} {'live compare':>18} "
            f"{'shadow seen/act':>15} {'false%':>6}"
        )
        for g in guardians:
            b = g.get("benchmark") or {}
            s = g.get("shadow") or {}
            cmp_ = (
                f"{b.get('live_slug')} {b.get('live_tpr_pct')}/{b.get('live_fpr_pct')}"
                if b.get("live_slug")
                else "none (policy)"
            )
            seen = f"{s.get('calls_seen', '-')}/{s.get('would_act', '-')}"
            lines.append(
                f"{g['id']:37} {g.get('state', '-'):10} {_n(b.get('tpr_pct')):>4} "
                f"{_n(b.get('fpr_pct')):>4} {_n(b.get('p95_us')):>6} {cmp_:>18} "
                f"{seen:>15} {_n(s.get('false_rate_pct')):>6}"
            )
    chk = doc.get("final_check")
    if chk:
        lines += [
            "",
            f"Final check on agent {chk['agent']}: over-limit transfer blocked={chk['blocked']}, "
            f"account number masked={chk['masked']}",
        ]
    if agents or guardians:
        lines += [
            "",
            f"Every row is tagged {TAG}. Rates are integer percent; kappa is in hundredths.",
        ]
        lines.append(
            "L3 shadow reads no_data until onboardings are stored (it informs, it never blocks)."
        )
        if any(a.get("model") == FAKE_LABEL for a in agents):
            lines.append(
                "Agent numbers are from the fake model (dev-fixture-replay): they show that the "
                "plumbing works, not how well a model reads a bank document."
            )
        lines.append(
            "Demo settings: guardian shadow window 1 day (product default 7); simulation review runs "
            "before the full gate; sim a/d/u = agree/disagree/unsure marks."
        )
    return lines


def _n(value: Any) -> str:
    return "-" if value is None else str(value)


# ---------------------------------------------------------------------------------- reset

_AGENT_TABLES = (
    ("factory_agent", "id"),
    ("factory_helper_draft", "agent_id"),
    ("gate_run", "agent_id"),
)
_GUARD_TABLES = (
    ("guardian_def", "def_id"),
    ("guardian_bench_run", "def_id"),
    ("guardian_shadow_finding", "def_id"),
    ("guardian_shadow_day", "def_id"),
)


def _delete(kit: Kit, table: str, column: str, value: str) -> int:
    ex = kit.runtime.adapters.executor
    n = ex.execute(f"DELETE FROM {ex.qualify(table)} WHERE {column} = :v", {"v": value})  # noqa: S608
    return max(int(n), 0)


def reset(kit: Kit) -> dict[str, int]:
    """Remove the rows and files of this module, and only those: an agent or guardian whose
    description carries the tag, the tagged internal documents, their folders and the results
    files. Append-only tables and the evidence chain are not touched."""
    from supervisor.guardian_factory import attach
    from supervisor.regkb import internal

    counts = {"agents": 0, "guardians": 0, "documents": 0, "rows": 0, "files": 0}
    for spec in AGENTS:
        rows = kit.env.store.versions(spec.agent_id)
        if not rows:
            continue
        if not all(TAG in str(r["definition"].get("description", "")) for r in rows):
            kit.say(f"[SKIP] {spec.agent_id} is not a showcase agent (no tag); left alone")
            continue
        for table, col in _AGENT_TABLES:
            counts["rows"] += _delete(kit, table, col, spec.agent_id)
        shutil.rmtree(kit.data_dir / "factory" / spec.agent_id, ignore_errors=True)
        counts["agents"] += 1
        kit.say(f"[OK] removed agent {spec.agent_id}")
    for def_id in (GUARD1, GUARD2):
        try:
            row = kit.ctx.guardian_defs.get(def_id)
        except SupervisorError:
            continue
        if TAG not in str(row["definition"].get("description", "")):
            kit.say(f"[SKIP] {def_id} is not a showcase guardian (no tag); left alone")
            continue
        for table, col in _GUARD_TABLES:
            counts["rows"] += _delete(kit, table, col, def_id)
        shutil.rmtree(kit.data_dir / "guardian_factory" / def_id, ignore_errors=True)
        counts["guardians"] += 1
        kit.say(f"[OK] removed guardian {def_id}")
    for row in [dict(r) for r in kit.ctx.state.query("regkb_internal_doc")]:
        if TAG not in str(row["title"]):
            continue
        doc_id = str(row["doc_id"])
        counts["rows"] += _delete(
            kit, "regkb_draft", "instrument_id", internal.instrument_id(doc_id)
        )
        counts["rows"] += _delete(kit, "regkb_internal_doc", "doc_id", doc_id)
        shutil.rmtree(kit.data_dir / "regkb" / "internal" / doc_id, ignore_errors=True)
        counts["documents"] += 1
        kit.say(f"[OK] removed internal document {internal.instrument_id(doc_id)}")
    for name in (RESULTS_NAME, MANIFEST_NAME):
        p = kit.showcase_dir / name
        if p.exists():
            p.unlink()
            counts["files"] += 1
    internal.invalidate_caches()
    attach.bump()
    kit.say(
        f"[OK] reset: {counts['agents']} agent(s), {counts['guardians']} guardian(s), "
        f"{counts['documents']} document(s), {counts['rows']} state row(s), {counts['files']} file(s). "
        "Append-only events and the evidence chain stay."
    )
    return counts


# ---------------------------------------------------------------------------------- entry


def validate_until(part: str | None, until: str | None) -> None:
    if until is None:
        return
    if part == "agents" and until not in AGENT_STATES:
        raise ShowcaseError(f"--until for agents is one of {', '.join(AGENT_STATES)}")
    if part == "guardians" and until not in GUARDIAN_STATES:
        raise ShowcaseError(f"--until for guardians is one of {', '.join(GUARDIAN_STATES)}")
    if part is None and until not in ("approved", "live"):
        raise ShowcaseError(
            "--until needs --part agents|guardians, except approved and live (they fit both)"
        )


def run(kit: Kit, part: str | None = None, until: str | None = None) -> dict[str, Any]:
    validate_until(part, until)
    if not kit.model_ready:
        kit.say(
            f"[INFO] LLM_BASE_URL is empty: the gate runs on the development fake model "
            f"(label: {FAKE_LABEL}); the law agent and the checklist drafter are skipped"
        )
    kit.say(
        "[INFO] the console must run with GOVERNANCE_ENABLED, AGENT_FACTORY, AGENT_FACTORY_GATE, "
        "REGKB_INTERNAL, LAWAGENT_ENABLED, DETECTORS_ENABLED, GUARDIAN_FACTORY and GUARDIAN_SHADOW "
        "set to 1 to show these rows"
    )
    errors: list[str] = []
    if part in (None, "agents"):
        try:
            run_agents(kit, until)
        except ShowcaseError as exc:
            errors.append(str(exc))
            kit.say(f"[FAIL] {exc}")
    if part in (None, "guardians"):
        try:
            run_guardians(kit, until)
        except ShowcaseError as exc:
            errors.append(str(exc))
            kit.say(f"[FAIL] {exc}")
    doc = read_json(results_path(kit), {})
    for line in render_tables(doc):
        kit.say(line)
    kit.say(f"[INFO] results written to {results_path(kit)}")
    if errors:
        raise ShowcaseError("; ".join(errors))
    return doc


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="python -m supervisor.demo.showcase factory",
        description="Showcase acts 3 and 4: two assessment agents and two guardians.",
    )
    p.add_argument("--part", choices=PARTS, default=None)
    p.add_argument(
        "--until",
        default=None,
        help="stop at a state: agents draft|tested|approved|live; guardians "
        "benchmarked|shadow|approved|live",
    )
    p.add_argument("--reset", action="store_true", help="remove only the rows of this showcase")
    p.add_argument(
        "--payments-agent", default=DEFAULT_PAYMENTS_AGENT, help="agent id for guardians"
    )
    p.add_argument("--data-dir", default=None)
    return p


def main(
    argv: Sequence[str] | None = None,
    *,
    settings: Settings | None = None,
    echo: Echo = default_echo,
    law_chat: Any = None,
) -> int:
    try:
        ns = build_parser().parse_args(list(argv) if argv is not None else None)
    except SystemExit as exc:
        return int(exc.code or 0) if isinstance(exc.code, int) else 2
    try:
        if settings is None:
            kwargs: dict[str, Any] = {"data_dir": Path(ns.data_dir)} if ns.data_dir else {}
            settings = load_settings(**kwargs)
        if not enabled(settings):
            echo(f"[FAIL] {OFF_TEXT}")
            return 1
        validate_until(ns.part, ns.until)
        with open_kit(settings, echo) as kit:
            kit.law_chat = law_chat
            kit.payments_agent = ns.payments_agent
            if ns.reset:
                reset(kit)
                return 0
            run(kit, ns.part, ns.until)
    except SupervisorError as exc:
        echo(f"[FAIL] {exc}")
        return 1
    except Exception as exc:  # noqa: BLE001 - a clean line and the fix, never a traceback
        echo(f"[FAIL] {type(exc).__name__}: {str(exc)[:300]}")
        return 1
    echo("[OK] done")
    return 0


if __name__ == "__main__":
    sys.exit(main())

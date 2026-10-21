"""Evaluation harness for the control catalogue and the task list (WP30; TEAM_BRIEF section 3,
adapted to a record layer).

    python -m supervisor.controls.harness [--split dev|held_out|both] [--fixtures DIR]
                                          [--write-baseline]

What it runs, with no model and no network (a record layer has no AI part: every result is the
output of deterministic code, so there is no mock path to label and no model card):

1. The golden set, ``tests/fixtures/controls/golden.jsonl``: 50 synthetic scenarios (30 dev, 20
   held-out) of five kinds: ``status`` (working, failing or no_data from source counts), ``bp``
   (the compliance figure), ``plan`` (the task set for each Decision 33 class and each band),
   ``gate`` (is the lifecycle move refused) and ``waive`` (may this person be the second person).
   Expected values come from an independent reference implementation
   (``tests/fixtures/controls/generate.py``). Never tune on the held-out split.
2. Determinism: the golden run twice gives the same hash.
3. Starter consistency: the 28 starter controls (``config/controls``) map only to obligation ids,
   risk ids, rules, packs, monitors and detectors that exist today; a rule limited to one agent is
   only used for that agent; every starter risk and every obligation the starter risks cite is
   covered by at least one control; the task templates name controls and packs that exist.
4. Adversarial probes: 24 cases the templates do not generate (a control with no evidence source,
   evidence from a retired rule, a mock pack, a waiver without a second person, a move with an open
   required task, duplicate ids, an obligation that does not exist, a class change in the middle
   of the lifecycle, type confusion, bad ids, formula injection, an import that is half bad ...).
   Reported as a separate row; a catalogue that passes only its own scenarios is NO-GO.

Expert rubrics (see ``docs/controls.md``): "compliance officer" (a control is working only on
runtime evidence, the figure is honest, the task set is right-sized and a high-risk class never
gets the light set) and "internal auditor (Three Lines)" (a lifecycle move is a gate, a waiver
needs a reason and a second person, a failing source beats a working one, shadow agents prove
nothing, every change is on the chain with hashes).

Numbers are integers (basis points, counts, microseconds) with Wilson 95 percent intervals.
GO / NO-GO thresholds are ILLUSTRATIVE; the bank sets its own.
"""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import sys
import time
from collections.abc import Callable, Sequence
from pathlib import Path
from types import SimpleNamespace
from typing import Any

from supervisor.controls import evidence as cev
from supervisor.controls.model import ControlError, evidence_capable, normalise
from supervisor.controls.refs import ControlRefs
from supervisor.controls.service import ControlService
from supervisor.risk.harness import _bp, load_golden, repo_catalogue, wilson_bp
from supervisor.tasks import model as tm
from supervisor.tasks.model import TaskError

THRESHOLDS_BP = {"golden": 10000, "starters": 10000, "adversarial": 10000, "determinism": 10000}
BASE_COMMIT = "316a039"
MIN_STARTER_CONTROLS = 25


def default_fixtures() -> Path:
    from supervisor.config import REPO_ROOT

    return REPO_ROOT / "tests" / "fixtures" / "controls"


def tasks_config_sha256() -> str:
    from supervisor.config import REPO_ROOT

    return hashlib.sha256((REPO_ROOT / "config" / "tasks.yaml").read_bytes()).hexdigest()


# ----------------------------------------------------------------------------- golden items


def run_item(item: dict[str, Any], cfg: tm.TaskConfig) -> dict[str, Any]:
    inp, task = item["input"], item["task"]
    if task == "status":
        r = cev.decide(
            inp["sources_n"], inp["working_n"], inp["failing_n"], inp["refs_n"], inp["supervised"]
        )
        return {"status": r.status, "reason": r.reason}
    if task == "bp":
        return {"bp": cev.compliance_bp(inp["working"], inp["in_scope"])}
    if task == "plan":
        p = tm.plan(cfg, inp["class"], inp["band"])
        return {
            "level": tm.effective_level(cfg, inp["class"], inp["band"]),
            "stages": tm.stages_in_use(cfg, inp["class"], inp["band"]),
            "required": [x.template.id for s in tm.STAGES for x in p[s] if x.required],
            "optional": [x.template.id for s in tm.STAGES for x in p[s] if not x.required],
        }
    if task == "gate":
        code, blockers = tm.move_refusal(inp["tasks"], inp["level"], cfg, inp["can_approve"])
        return {"code": code, "blockers": blockers}
    if task == "waive":
        return {
            "refusal": tm.waive_refusal(
                inp["requester"] or None, inp["approver"], inp["kind"], inp["can_approve"]
            )
        }
    raise ControlError(f"unknown golden task {task!r}")


def run_golden(items: Sequence[dict[str, Any]], split: str | None = None) -> dict[str, Any]:
    cfg = tm.load_config()
    chosen = [i for i in items if split in (None, i["split"])]
    misses: list[dict[str, Any]] = []
    by_task: dict[str, list[int]] = {}
    lat: list[int] = []
    digest = hashlib.sha256()
    for item in chosen:
        t0 = time.perf_counter_ns()
        got = run_item(item, cfg)
        lat.append((time.perf_counter_ns() - t0) // 1000)
        ok = got == item["expected"]
        ok_n, all_n = by_task.setdefault(item["task"], [0, 0])
        by_task[item["task"]] = [ok_n + (1 if ok else 0), all_n + 1]
        digest.update(json.dumps([item["id"], got], sort_keys=True).encode())
        if not ok:
            misses.append({"id": item["id"], "task": item["task"], "got": got})
    n = len(chosen)
    k = n - len(misses)
    return {
        "n": n,
        "correct": k,
        "accuracy_bp": _bp(k, n),
        "accuracy_ci_bp": list(wilson_bp(k, n)),
        "by_task": {
            t: {"correct": a, "n": b, "bp": _bp(a, b)} for t, (a, b) in sorted(by_task.items())
        },
        "failure_taxonomy": {"misses": misses},
        "latency_us_max": max(lat, default=0),
        "latency_us_total": sum(lat),
        "result_hash": digest.hexdigest(),
    }


# ----------------------------------------------------------------------------- starter consistency


def check_starters(directory: Path | None = None) -> dict[str, Any]:
    """Every starter control maps to ids that exist today, and the starters cover what the
    starter risks cite (the consistency check)."""
    from supervisor.config import REPO_ROOT
    from supervisor.gateway.policy import load_policy_dir
    from supervisor.inventory.fill import fill_from_manifests
    from supervisor.inventory.service import AGENTS_DIR, BASELINE
    from supervisor.risk.service import RiskService

    directory = directory or REPO_ROOT / "config" / "controls"
    risk_docs = [
        d
        for f in sorted((REPO_ROOT / "config" / "risks").glob("*.yaml"))
        for d in RiskService.parse_import(f.read_text(encoding="utf-8"), f.name)
    ]
    risk_ids = {d["id"] for d in risk_docs}
    cited = {t for d in risk_docs for k, t in d["links"] if k == "matrix"}
    policy = load_policy_dir(REPO_ROOT / "policies")
    scopes = {r.id: r.agent_scope for r in policy.doc.rules}
    refs = ControlRefs(repo_catalogue(), risks=lambda: risk_ids, rule_scopes=lambda: scopes)
    g = fill_from_manifests(AGENTS_DIR, BASELINE, {}, root=REPO_ROOT)
    problems: list[str] = []
    n_controls = n_maps = 0
    seen: set[str] = set()
    covered_obl: set[str] = set()
    covered_risk: set[str] = set()
    for f in sorted(directory.glob("*.yaml")):
        for doc in ControlService.parse_import(f.read_text(encoding="utf-8"), f.name):
            n_controls += 1
            cid = doc["id"]
            if cid in seen:
                problems.append(f"{cid}: id used twice")
            seen.add(cid)
            try:
                fields = normalise(doc, source="starter")
            except ControlError as exc:
                problems.append(f"{cid}: {exc}")
                continue
            if fields["status"] == "active":
                kinds = {k for k, _ in doc["maps"]}
                if not kinds & {"matrix", "risk"}:
                    problems.append(f"{cid}: covers nothing")
                if not kinds & {"rule", "pack", "monitor", "detector", "document"}:
                    problems.append(f"{cid}: no evidence source")
                elif fields["implemented_by"] == "product" and not any(
                    evidence_capable(k, t) for k, t in doc["maps"]
                ):
                    problems.append(f"{cid}: a product control with only reference sources")
            for agent in fields["scope_agents"]:
                if agent != "*" and g.by_name("system", agent) is None:
                    problems.append(f"{cid}: agent {agent} is not in the manifests")
            for kind, target in doc["maps"]:
                n_maps += 1
                if not refs.exists(kind, target):
                    problems.append(f"{cid}: {kind} {target} does not exist")
                if kind == "matrix" and fields["status"] == "active":
                    covered_obl.add(target)
                if kind == "risk" and fields["status"] == "active":
                    covered_risk.add(target)
                if kind == "rule":
                    sc = scopes.get(target)
                    scope = fields["scope_agents"]
                    if sc not in (None, "*") and (scope == ["*"] or set(scope) - set(sc)):
                        problems.append(f"{cid}: rule {target} is not in scope for {scope}")
    if n_controls < MIN_STARTER_CONTROLS:
        problems.append(f"only {n_controls} starter controls (at least {MIN_STARTER_CONTROLS})")
    for rid in sorted(risk_ids - covered_risk):
        problems.append(f"{rid}: no active starter control covers this starter risk")
    for obl in sorted(cited - covered_obl):
        problems.append(f"{obl}: cited by a starter risk, covered by no starter control")
    # the task templates must name controls and packs that exist
    cfg = tm.load_config()
    for t in cfg.templates:
        if t.evidence_kind == "control" and t.evidence_ref not in seen:
            problems.append(f"task {t.id}: control {t.evidence_ref} is not in the starters")
        if t.evidence_kind == "pack" and not refs.exists("pack", str(t.evidence_ref)):
            problems.append(f"task {t.id}: pack {t.evidence_ref} does not exist")
    bad = {p.split(":")[0] for p in problems}
    return {
        "controls": n_controls,
        "maps": n_maps,
        "risks_covered": len(covered_risk & risk_ids),
        "obligations_covered": len(cited & covered_obl),
        "problems": problems,
        "bp": _bp(max(0, n_controls - len(bad)), n_controls),
    }


# ----------------------------------------------------------------------------- adversarial


def _person(user: str, *roles: str, kind: str = "user") -> SimpleNamespace:
    return SimpleNamespace(user_id=user, kind=kind, roles=frozenset(roles))


OWNER = _person("olga", "owner")
REVIEWER = _person("rene", "reviewer")
APPROVER = _person("amir", "approver")
ADMIN = _person("ada", "admin")


def _refused(fn: Callable[[], Any], exc: type[Exception], fragment: str = "") -> bool:
    try:
        fn()
    except exc as e:
        return fragment in str(e)
    return False


def _finish_stage(env: Any, agent: str, who: Any = ADMIN) -> None:
    stage = env.tasks.current_stage(agent)
    for r in env.tasks.rows_of(agent):
        if r["stage"] != stage or r["status"] not in tm.OPEN_STATUSES or r["kind"] == "move":
            continue
        env.tasks.done(r["task_id"], who, "doc-ref" if r["evidence_kind"] == "document" else None)
    for r in env.tasks.rows_of(agent):
        if r["stage"] == stage and r["kind"] == "move" and r["status"] in tm.OPEN_STATUSES:
            env.tasks.done(r["task_id"], who)


def probes() -> list[tuple[str, Callable[[Any], bool]]]:
    def p_no_source(env: Any) -> bool:
        return _refused(lambda: env.control("C1", evidence=[]), ControlError, "evidence source")

    def p_retired_rule(env: Any) -> bool:
        env.agent("pay")
        env.control("C1", evidence=[("rule", "PAY-02"), ("pack", "pack_a")])
        env.pack("pay", "pack_a", "ok", env.window_time())
        env.rules.discard("PAY-02")
        env.controls.run_status()
        c = env.controls.agent_compliance("pay")["controls"][0]
        return c["status"] == "failing"

    def p_mock_pack(env: Any) -> bool:
        env.agent("pay")
        env.control("C1", evidence=[("pack", "pack_a")])
        env.pack("pay", "pack_a", "ok", env.window_time(), mock=True)
        env.controls.run_status()
        return env.controls.agent_compliance("pay")["controls"][0]["status"] == "no_data"

    def p_waiver_one_person(env: Any) -> bool:
        env.agent("pay")
        env.classify("pay", "not_high_risk", "low")
        env.tasks.generate("pay", ADMIN)
        tid = env.tasks.rows_of("pay")[0]["task_id"]
        env.tasks.request_waive(tid, REVIEWER, "pilot")
        same = _refused(
            lambda: env.tasks.approve_waive(tid, _person("rene", "admin")), TaskError, "different"
        )
        row = env.adapters.state.get("task", {"task_id": tid})
        env.adapters.state.update(
            "task",
            {"task_id": tid},
            {"status": "waived", "waive_approved_by": "rene"},
            row["row_version"],
        )  # a forged row: the audit query must see it
        return same and len(env.tasks.integrity_problems()) == 1

    def p_move_open_task(env: Any) -> bool:
        env.agent("pay")
        env.classify("pay", "not_high_risk", "low")
        env.tasks.generate("pay", ADMIN)
        move = next(r for r in env.tasks.rows_of("pay") if r["kind"] == "move")
        return _refused(lambda: env.tasks.done(move["task_id"], OWNER), TaskError, "refused")

    def p_duplicate_ids(env: Any) -> bool:
        env.control("C1")
        again = _refused(lambda: env.control("C1"), ControlError, "already exists")
        doc = {
            "title": "T",
            "objective": "O",
            "control_type": "preventive",
            "implemented_by": "product",
            "owner": "ops",
            "status": "draft",
        }
        res = env.controls.import_docs([{"id": "D1", **doc}, {"id": "D1", **doc}], "u")
        return again and any("used twice" in e for e in res.errors) and res.created == 0

    def p_unknown_obligation(env: Any) -> bool:
        return _refused(
            lambda: env.control("C1", covers=[("matrix", "VN-NOT-REAL-01")]),
            ControlError,
            "does not exist",
        )

    def p_class_change(env: Any) -> bool:
        env.agent("pay")
        env.classify("pay", "not_high_risk", "low")
        env.tasks.generate("pay", ADMIN)
        before = {r["template_id"] for r in env.tasks.rows_of("pay")}
        env.classify("pay", "high_risk", "low")
        env.tasks.generate("pay", ADMIN)
        up = {r["template_id"]: r for r in env.tasks.rows_of("pay")}
        env.classify("pay", "not_high_risk", "low")
        env.tasks.generate("pay", ADMIN)
        down = {r["template_id"]: r for r in env.tasks.rows_of("pay")}
        return (
            before <= set(up)
            and set(up) == set(down)
            and all(r["required"] == up[t]["required"] for t, r in down.items())
        )

    def p_covers_nothing(env: Any) -> bool:
        return _refused(lambda: env.control("C1", covers=[]), ControlError, "cover at least one")

    def p_rule_scope(env: Any) -> bool:
        return _refused(
            lambda: env.control("C1", agents=["*"]), ControlError, "limited to pay"
        ) and _refused(lambda: env.control("C2", agents=["svc"]), ControlError, "not in scope")

    def p_shadow(env: Any) -> bool:
        env.agent("pay", "SHADOW")
        env.control("C1")
        env.verdict("pay", "PAY-02", "block", env.window_time())
        env.controls.run_status()
        c = env.controls.agent_compliance("pay")["controls"][0]
        return c["status"] == "no_data" and c["reason"] == "no_supervised_agent"

    def p_stale(env: Any) -> bool:
        env.agent("pay")
        env.control("C1")
        env.verdict("pay", "PAY-02", "block", env.window_time())
        env.controls.run_status()
        later = env.adapters.clock.now() + dt.timedelta(days=60)
        env.controls.clock = SimpleNamespace(now=lambda: later)
        c = env.controls.agent_compliance("pay")["controls"][0]
        return c["status"] == "no_data" and c["reason"] == "stale"

    def p_draft_control(env: Any) -> bool:
        env.agent("pay")
        rid = env.risk("r", "pay", [("matrix", "OB-1")])
        env.controls.create(
            {
                "title": "T",
                "objective": "O",
                "control_type": "preventive",
                "implemented_by": "product",
                "owner": "ops",
                "status": "draft",
                "agents": ["pay"],
            },
            "u",
            control_id="C1",
            maps=[("risk", rid), ("rule", "PAY-02")],
        )
        env.verdict("pay", "PAY-02", "block", env.window_time())
        env.svc.run_evidence()
        return env.svc.get(rid)["evidence_state"] == "no_evidence"

    def p_document_only(env: Any) -> bool:
        env.agent("pay")
        env.control(
            "C1",
            evidence=[("document", f"doc-{i}") for i in range(5)] + [("detector", "cccd")],
        )
        env.controls.run_status()
        c = env.controls.agent_compliance("pay")["controls"][0]
        return c["status"] == "no_data" and c["reason"] == "reference_only"

    def p_csv(env: Any) -> bool:
        env.control("C1", title='=HYPERLINK("http://x","y")', owner="@evil")
        controls_csv, _ = env.controls.export_csv()
        return "'=HYPERLINK" in controls_csv and "'@evil" in controls_csv

    def p_types(env: Any) -> bool:
        base = {
            "title": "T",
            "objective": "O",
            "control_type": "preventive",
            "implemented_by": "product",
            "owner": "ops",
            "status": "draft",
        }
        bad = [
            {"title": ["x"]},
            {"status": 5},
            {"agents": "pay"},
            {"agents": [5]},
            {"review_date": 20270101},
            {"control_type": None},
            {"owner": {"a": 1}},
        ]
        return all(_refused(lambda b=b: normalise(base | b), ControlError) for b in bad)

    def p_bad_ids(env: Any) -> bool:
        ids = ["../x", "a" * 65, "", "a b", "x;drop", "é"]
        ok = all(_refused(lambda i=i: env.controls.get(i), ControlError, "control id") for i in ids)
        ok = ok and _refused(lambda: env.tasks.done("../x", OWNER), TaskError, "task id")
        return ok and _refused(
            lambda: env.controls.add_map("C1", "rule", "bad target", "u"), ControlError
        )

    def p_second_person(env: Any) -> bool:
        env.agent("pay")
        env.classify("pay", "not_high_risk", "low")
        env.tasks.generate("pay", ADMIN)
        tid = env.tasks.rows_of("pay")[0]["task_id"]
        env.tasks.request_waive(tid, REVIEWER, "pilot")
        bot = _person("svc", "admin", kind="service")
        return (
            _refused(lambda: env.tasks.approve_waive(tid, bot), TaskError, "signed-in")
            and _refused(
                lambda: env.tasks.approve_waive(tid, OWNER), TaskError, "approver or admin"
            )
            and env.tasks.approve_waive(tid, APPROVER)["status"] == "waived"
        )

    def p_waive_reason(env: Any) -> bool:
        env.agent("pay")
        env.classify("pay", "not_high_risk", "low")
        env.tasks.generate("pay", ADMIN)
        tid = env.tasks.rows_of("pay")[0]["task_id"]
        return all(
            _refused(lambda r=r: env.tasks.request_waive(tid, REVIEWER, r), TaskError)
            for r in ("", "   ", None, 5, "x" * 1001)
        )

    def p_high_move(env: Any) -> bool:
        env.agent("pay")
        env.classify("pay", "high_risk", "high")
        env.tasks.generate("pay", ADMIN)
        for r in env.tasks.rows_of("pay"):
            if r["kind"] != "move":
                env.tasks.done(r["task_id"], OWNER, "doc")
        move = next(r for r in env.tasks.rows_of("pay") if r["kind"] == "move")
        refused = _refused(
            lambda: env.tasks.done(move["task_id"], OWNER), TaskError, "approver or an admin"
        )
        env.tasks.done(move["task_id"], APPROVER)
        return refused and env.tasks.current_stage("pay") == "design"

    def p_import_atomic(env: Any) -> bool:
        good = {
            "id": "G1",
            "title": "T",
            "objective": "O",
            "control_type": "preventive",
            "implemented_by": "product",
            "owner": "ops",
            "status": "active",
            "review_date": "2027-04-20",
            "agents": ["pay"],
            "maps": [("matrix", "OB-1"), ("rule", "PAY-02")],
        }
        bad = {**good, "id": "G2", "maps": [("matrix", "NOPE"), ("rule", "PAY-02")]}
        res = env.controls.import_docs([good, bad], "u")
        return bool(res.errors) and env.controls.list_controls() == []

    def p_launch_gate(env: Any) -> bool:
        from supervisor.assurance.gates import task_launch_items
        from supervisor.onboard.launch import _with_tasks
        from supervisor.onboard.models import LaunchReport

        env.agent("pay")
        env.classify("pay", "not_high_risk", "low")
        env.tasks.generate("pay", ADMIN)
        rows = env.tasks.open_required("pay")
        report = LaunchReport.model_construct(go=True, reasons=["all integration checks pass"])
        out = _with_tasks(report, "pay", rows, env.settings)
        clean = _with_tasks(report, "pay", [], env.settings)
        return (
            not out.go
            and out.task_reasons == task_launch_items(rows)
            and bool(rows)
            and clean.go
            and clean.task_reasons == []
        )

    def p_unknown_class(env: Any) -> bool:
        env.agent("pay")
        env.classify("pay", "made_up_class", "nonsense")
        i = env.tasks.agent_inputs("pay")
        return (i["d33_class"], i["band"], i["level"]) == ("unclassified", "high", "high")

    def p_evidence_for_done(env: Any) -> bool:
        env.agent("pay")
        env.classify("pay", None, "low")
        for pack in ("owasp_agentic_redteam", "pii_canary", "indirect_injection_vi"):
            env.pack("pay", pack, "ok", env.window_time())
        env.tasks.generate("pay", ADMIN)
        purpose = next(r for r in env.tasks.rows_of("pay") if r["template_id"] == "INI-PURPOSE")
        no_ref = _refused(
            lambda: env.tasks.done(purpose["task_id"], OWNER), TaskError, "document reference"
        )
        env.control("CTL-PII-MASK", evidence=[("rule", "PAY-02")])
        while env.tasks.current_stage("pay") != "operation":
            _finish_stage(env, "pay")
        ops = next(r for r in env.tasks.rows_of("pay") if r["template_id"] == "OPS-MASK")
        no_data = _refused(lambda: env.tasks.done(ops["task_id"], OWNER), TaskError, "no_data")
        env.verdict("pay", "PAY-02", "block", env.window_time())
        env.controls.run_status()
        return no_ref and no_data and env.tasks.done(ops["task_id"], OWNER)["status"] == "done"

    return [
        ("control_with_no_evidence_source_refused", p_no_source),
        ("evidence_from_a_retired_rule_is_failing", p_retired_rule),
        ("mock_pack_result_is_not_evidence", p_mock_pack),
        ("waiver_without_a_second_person_refused_and_audited", p_waiver_one_person),
        ("lifecycle_move_with_open_required_task_refused", p_move_open_task),
        ("duplicate_control_ids_refused", p_duplicate_ids),
        ("obligation_that_does_not_exist_refused", p_unknown_obligation),
        ("class_change_mid_lifecycle_is_additive_never_relaxes", p_class_change),
        ("active_control_that_covers_nothing_refused", p_covers_nothing),
        ("rule_limited_to_another_agent_refused", p_rule_scope),
        ("shadow_agent_evidence_not_counted", p_shadow),
        ("stale_status_is_no_data", p_stale),
        ("draft_control_gives_a_risk_no_evidence", p_draft_control),
        ("documents_and_detectors_never_make_a_control_work", p_document_only),
        ("csv_formula_injection_neutralised", p_csv),
        ("type_confusion_refused", p_types),
        ("bad_ids_and_targets_refused", p_bad_ids),
        ("second_person_must_be_a_signed_in_approver", p_second_person),
        ("waiver_without_a_reason_refused", p_waive_reason),
        ("high_level_move_needs_an_approver", p_high_move),
        ("half_bad_import_writes_nothing", p_import_atomic),
        ("launch_refuses_go_with_an_open_required_task", p_launch_gate),
        ("unknown_class_and_tier_sized_as_high", p_unknown_class),
        ("done_needs_its_evidence", p_evidence_for_done),
    ]


def run_adversarial() -> dict[str, Any]:
    from supervisor.controls.harness_env import CtlEnv

    results: dict[str, bool] = {}
    for name, fn in probes():
        env = CtlEnv()
        try:
            results[name] = bool(fn(env))
        except Exception as exc:  # noqa: BLE001 - a crash is a failed probe, reported by name
            results[name] = False
            print(f"[probe {name}] {type(exc).__name__}: {exc}"[:300])  # noqa: T201
        finally:
            env.close()
    k = sum(1 for v in results.values() if v)
    return {
        "n": len(results),
        "passed": k,
        "bp": _bp(k, len(results)),
        "ci_bp": list(wilson_bp(k, len(results))),
        "failed": sorted(n for n, v in results.items() if not v),
        "probes": results,
    }


# ----------------------------------------------------------------------------- run and report


def run_all(fixtures: Path, splits: Sequence[str]) -> dict[str, Any]:
    items = load_golden(fixtures / "golden.jsonl")
    out: dict[str, Any] = {"golden": {s: run_golden(items, s) for s in splits}}
    first = run_golden(items)
    second = run_golden(items)
    out["determinism"] = {
        "bp": 10000 if first["result_hash"] == second["result_hash"] else 0,
        "result_hash": first["result_hash"],
    }
    out["starters"] = check_starters()
    out["adversarial"] = run_adversarial()
    verdicts = {}
    for s in splits:
        verdicts[f"golden_{s}"] = (
            "GO" if out["golden"][s]["accuracy_bp"] >= THRESHOLDS_BP["golden"] else "NO-GO"
        )
    verdicts["determinism"] = (
        "GO" if out["determinism"]["bp"] >= THRESHOLDS_BP["determinism"] else "NO-GO"
    )
    verdicts["starters"] = "GO" if not out["starters"]["problems"] else "NO-GO"
    verdicts["adversarial"] = (
        "GO" if out["adversarial"]["bp"] >= THRESHOLDS_BP["adversarial"] else "NO-GO"
    )
    out["verdicts"] = verdicts
    out["thresholds_bp"] = THRESHOLDS_BP
    out["thresholds_note"] = "ILLUSTRATIVE until the bank sets them"
    return out


def main(argv: Sequence[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="python -m supervisor.controls.harness", description=__doc__)
    ap.add_argument("--split", choices=("dev", "held_out", "both"), default="both")
    ap.add_argument("--fixtures", help="fixture folder (default: tests/fixtures/controls)")
    ap.add_argument("--write-baseline", action="store_true", help="rewrite baseline.json")
    args = ap.parse_args(argv)
    fixtures = Path(args.fixtures) if args.fixtures else default_fixtures()
    splits = ("dev", "held_out") if args.split == "both" else (args.split,)
    res = run_all(fixtures, splits)
    for s in splits:
        g = res["golden"][s]
        print(  # noqa: T201
            f"[{s}] n={g['n']} accuracy={g['accuracy_bp']}bp {g['accuracy_ci_bp']} "
            f"by_task={ {t: v['bp'] for t, v in g['by_task'].items()} } "
            f"latency_us_max={g['latency_us_max']}"
        )
    a = res["adversarial"]
    print(f"[adversarial] {a['passed']}/{a['n']} {a['ci_bp']} failed={a['failed']}")  # noqa: T201
    st = res["starters"]
    print(  # noqa: T201
        f"[starters] controls={st['controls']} maps={st['maps']} "
        f"risks_covered={st['risks_covered']} obligations_covered={st['obligations_covered']} "
        f"problems={st['problems']}"
    )
    print(f"[determinism] {res['determinism']['bp']}bp")  # noqa: T201
    bad = 0
    for name, v in res["verdicts"].items():
        print(f"    {name}: {v}")  # noqa: T201
        bad += v != "GO"
    if args.write_baseline:
        (fixtures / "baseline.json").write_text(
            json.dumps(
                {
                    "note": "Recorded by `python -m supervisor.controls.harness --write-baseline`. "
                    "tests/controls/test_harness.py fails if a metric drops below this.",
                    "date": dt.date.today().isoformat(),
                    "base_commit": BASE_COMMIT,
                    "branch": "wp30-controls",
                    "tasks_config_sha256": tasks_config_sha256(),
                    "results": _baseline_view(res),
                },
                indent=2,
                sort_keys=True,
            )
            + "\n",
            encoding="utf-8",
            newline="\n",
        )
        print("[OK] wrote baseline.json")  # noqa: T201
    print("[OK] all GO" if not bad else f"[FAIL] {bad} NO-GO verdict(s)")  # noqa: T201
    return 1 if bad else 0


def _baseline_view(res: dict[str, Any]) -> dict[str, Any]:
    """The numbers the regression test compares (no latency: it varies by machine)."""
    return {
        "golden": {
            s: {
                "n": g["n"],
                "correct": g["correct"],
                "accuracy_bp": g["accuracy_bp"],
                "accuracy_ci_bp": g["accuracy_ci_bp"],
                "by_task": g["by_task"],
                "result_hash": g["result_hash"],
            }
            for s, g in res["golden"].items()
        },
        "determinism_bp": res["determinism"]["bp"],
        "starters": {k: res["starters"][k] for k in ("controls", "maps", "risks_covered", "bp")},
        "adversarial": {k: res["adversarial"][k] for k in ("n", "passed", "bp")},
        "verdicts": res["verdicts"],
    }


if __name__ == "__main__":
    sys.exit(main())

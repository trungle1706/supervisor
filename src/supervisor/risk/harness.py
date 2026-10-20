"""Evaluation harness for the risk register (WP29; TEAM_BRIEF section 3, adapted to a record layer).

    python -m supervisor.risk.harness [--split dev|held_out|both] [--fixtures DIR]
                                      [--write-baseline]

What it runs, with no model and no network (a record layer has no AI part: every result is the
output of deterministic code, so there is no mock path to label and no model card):

1. The golden set, ``tests/fixtures/risk/golden.jsonl``: 50 synthetic scenarios (30 dev, 20
   held-out) of four kinds: ``score`` (likelihood x impact and band), ``inherit`` (agent level
   over an inventory graph), ``evidence`` (the evidence rule) and ``link`` (does the target of a
   link exist). Expected values come from an independent reference implementation
   (``tests/fixtures/risk/generate.py``). Never tune on the held-out split.
2. Determinism: the golden run twice gives the same hash.
3. Starter consistency: every starter risk in ``config/risks`` links to rule ids, obligations,
   packs and monitors that exist today; an agent risk names a real agent; a rule it links is in
   scope for that agent; a node anchor resolves in the inventory built from the manifests.
4. Adversarial probes: 20 cases the templates do not generate (cycles, a 3000-deep chain,
   retired nodes, draft and retired risks, conflicting treatments, a SHADOW agent's evidence,
   a rule that no longer exists, mock results, stale evidence, type confusion, bad ids, CSV
   formula injection). Reported as a separate row; a register that passes only its own
   scenarios is NO-GO.

Expert rubrics (see ``docs/risk-register.md``): "operational risk manager" (is the score and the
band right; is the agent as risky as the worst risk it can reach; do retired or draft things
stay out) and "internal auditor (Three Lines)" (is a lowered residual score backed by working
evidence with a recorded reason; does a broken control raise it again; does every link point at
something that exists).

Numbers are integers (basis points, counts, microseconds) with Wilson 95 percent intervals.
GO / NO-GO thresholds are ILLUSTRATIVE; the bank sets its own.
"""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import math
import sys
import tempfile
import time
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import Any

from supervisor.inventory.graph import Graph
from supervisor.inventory.model import Edge, Node, node_id_for
from supervisor.risk import evidence as ev
from supervisor.risk import inherit
from supervisor.risk.model import RiskConfig, RiskError, Thresholds, band_of, score_of
from supervisor.risk.refs import RefCatalogue, build_catalogue

THRESHOLDS_BP = {"golden": 10000, "starters": 10000, "adversarial": 10000, "determinism": 10000}
Z95 = 1.959964
BASE_COMMIT = "3aed7f9"


def wilson_bp(successes: int, n: int) -> tuple[int, int]:
    """Wilson 95 percent interval of a proportion, in integer basis points."""
    if n <= 0:
        return (0, 10000)
    p = successes / n
    z2 = Z95 * Z95
    denom = 1 + z2 / n
    centre = (p + z2 / (2 * n)) / denom
    half = Z95 * math.sqrt(p * (1 - p) / n + z2 / (4 * n * n)) / denom
    return (
        max(0, math.floor((centre - half) * 10000)),
        min(10000, math.ceil((centre + half) * 10000)),
    )


def _bp(part: int, whole: int) -> int:
    return 10000 if whole == 0 else part * 10000 // whole


def default_fixtures() -> Path:
    from supervisor.config import REPO_ROOT

    return REPO_ROOT / "tests" / "fixtures" / "risk"


def load_golden(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]


class _NoState:
    """Enough of a state store for the catalogue: no deployed rule, so the policy folder is read."""

    def query(self, *_a: Any, **_k: Any) -> list[Any]:
        return []

    def get(self, *_a: Any, **_k: Any) -> None:
        return None


def repo_catalogue() -> RefCatalogue:
    return build_catalogue(_NoState(), None)


# ----------------------------------------------------------------------------- golden items


def _graph_of(scn: dict[str, Any]) -> tuple[Graph, list[inherit.RiskPoint]]:
    g = Graph()
    for kind, name, status in scn["nodes"]:
        attrs = {"role": "agent"} if kind == "system" else {}
        g.add_node(Node(kind, name, status=status, attrs=attrs))
    for sk, sn, dk, dn, ek, active in scn["edges"]:
        g.add_edge(Edge(node_id_for(sk, sn), node_id_for(dk, dn), ek, "manual", "h", active))
    points = []
    for n, r in enumerate(scn["risks"]):
        kind, name = r["anchor"]
        points.append(
            inherit.RiskPoint(
                risk_id=f"r{n}",
                anchor=node_id_for(kind, name),
                agent_id=name if kind == "system" else None,
                status=r["status"],
                inherent_score=r["l"] * r["i"],
                residual_score=r["rl"] * r["ri"],
            )
        )
    return g, points


def run_item(item: dict[str, Any], cat: RefCatalogue) -> dict[str, Any]:
    inp, task = item["input"], item["task"]
    th = Thresholds()
    if task == "score":
        s = score_of(inp["likelihood"], inp["impact"])
        return {"score": s, "band": band_of(s, th)}
    if task == "inherit":
        g, points = _graph_of(inp)
        out = inherit.compute(g, points, th)
        return {"agents": {a: [x.inherent_level, x.residual_level] for a, x in sorted(out.items())}}
    if task == "evidence":
        c = ev.Counts(**inp["counts"])
        cfg = RiskConfig(th, inp.get("min_working", 1))
        d = ev.assess(inp["treatment"], tuple(inp["inherent"]), tuple(inp["declared"]), c, cfg)
        return {"state": d.state, "reason": d.reason, "residual": list(d.residual)}
    if task == "link":
        return {"exists": cat.exists(inp["kind"], inp["target"])}
    raise RiskError(f"unknown golden task {task!r}")


def run_golden(items: Sequence[dict[str, Any]], split: str | None = None) -> dict[str, Any]:
    cat = repo_catalogue()
    chosen = [i for i in items if split in (None, i["split"])]
    misses: list[dict[str, Any]] = []
    by_task: dict[str, list[int]] = {}
    lat: list[int] = []
    digest = hashlib.sha256()
    for item in chosen:
        t0 = time.perf_counter_ns()
        got = run_item(item, cat)
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
    """Every starter risk links to ids that exist today (the consistency check)."""
    from supervisor.config import REPO_ROOT
    from supervisor.gateway.policy import load_policy_dir
    from supervisor.inventory.fill import fill_from_manifests
    from supervisor.inventory.service import AGENTS_DIR, BASELINE
    from supervisor.risk.model import LINK_KINDS
    from supervisor.risk.service import RiskService

    directory = directory or REPO_ROOT / "config" / "risks"
    cat = repo_catalogue()
    g = fill_from_manifests(AGENTS_DIR, BASELINE, {}, root=REPO_ROOT)
    policy = load_policy_dir(REPO_ROOT / "policies")
    scope = {r.id: r.agent_scope for r in policy.doc.rules}
    problems: list[str] = []
    n_risks = n_links = 0
    seen: set[str] = set()
    for f in sorted(directory.glob("*.yaml")):
        for doc in RiskService.parse_import(f.read_text(encoding="utf-8"), f.name):
            n_risks += 1
            rid = doc["id"]
            if rid in seen:
                problems.append(f"{rid}: id used twice")
            seen.add(rid)
            agent = doc.get("agent_id")
            if agent and g.by_name("system", agent) is None:
                problems.append(f"{rid}: agent {agent} is not in the manifests")
            if doc.get("node_id") and doc["node_id"] not in g.nodes:
                problems.append(f"{rid}: node does not resolve in the manifest inventory")
            for kind, target in doc["links"]:
                n_links += 1
                if kind not in LINK_KINDS or not cat.exists(kind, target):
                    problems.append(f"{rid}: {kind} {target} does not exist")
                if kind == "rule" and agent:
                    sc = scope.get(target)
                    if sc not in (None, "*") and agent not in (sc or []):
                        problems.append(f"{rid}: rule {target} is not in scope for {agent}")
    return {
        "risks": n_risks,
        "links": n_links,
        "problems": problems,
        "bp": _bp(n_risks - len({p.split(":")[0] for p in problems}), n_risks),
    }


# ----------------------------------------------------------------------------- adversarial


def _agent_graph(*edges: tuple[str, str, str, str]) -> Graph:
    g = Graph()
    names: set[tuple[str, str]] = set()
    for sk, sn, dk, dn in edges:
        names |= {(sk, sn), (dk, dn)}
    for k, n in sorted(names):
        g.add_node(Node(k, n, attrs={"role": "agent"} if k == "system" else {}))
    for sk, sn, dk, dn in edges:
        g.add_edge(Edge(node_id_for(sk, sn), node_id_for(dk, dn), "uses", "manual", "h"))
    return g


def _pt(rid: str, kind: str, name: str, score: int, status: str = "active") -> inherit.RiskPoint:
    return inherit.RiskPoint(rid, node_id_for(kind, name), None, status, score, score)


def _expect_error(fn: Callable[[], Any], fragment: str = "") -> bool:
    try:
        fn()
    except RiskError as exc:
        return fragment in str(exc)
    return False


class _Env:
    """A temporary SQLite store with a risk service, agents and seeded runtime rows."""

    def __init__(self) -> None:
        from supervisor.adapters.factory import build_adapters
        from supervisor.config import load_settings
        from supervisor.jobs import bootstrap_schema
        from supervisor.risk.service import RiskService

        self._tmp = tempfile.TemporaryDirectory()
        self.settings = load_settings(
            sql_backend="sqlite",
            data_dir=Path(self._tmp.name) / "data",
            llm_base_url="",
            risk_register_enabled=True,
        )
        self.adapters = build_adapters(self.settings)
        bootstrap_schema.run(self.settings, self.adapters)
        self.rules = {"PAY-02", "PAY-03"}
        cat = RefCatalogue(
            obligations=lambda: ["OB-1"],
            rules=lambda: self.rules,
            packs=lambda: ["pack_a"],
            monitors=lambda: ["oversight"],
            case_exists=lambda c: False,
        )
        self.svc = RiskService.from_adapters(self.adapters)
        self.svc.catalogue = cat
        self.n = 0

    def close(self) -> None:
        self.adapters.close()
        self._tmp.cleanup()

    def agent(self, agent_id: str, gate_state: str = "RUNNING") -> None:
        now = self.adapters.clock.now()
        self.adapters.state.insert(
            "agent",
            {
                "agent_id": agent_id,
                "name": agent_id,
                "owner_team": "t",
                "owner_user": "u",
                "risk_tier": "high",
                "host_type": "python_inprocess",
                "plug_point": "gate_hook",
                "model_family": "qwen",
                "status": "active",
                "gate_state": gate_state,
                "created_at": now,
            },
        )

    def verdict(self, agent_id: str, rule_id: str, action: str, when: dt.datetime) -> None:
        self.n += 1
        self.adapters.tables.append(
            "verdict",
            [
                {
                    "verdict_id": f"v{self.n}",
                    "ts": when,
                    "agent_id": agent_id,
                    "tier": 0,
                    "checker_id": "gate",
                    "is_mock": False,
                    "advisory": False,
                    "label": "hit",
                    "action": action,
                    "rule_id": rule_id,
                }
            ],
        )

    def pack(
        self, agent_id: str, pack_id: str, status: str, when: dt.datetime, mock: bool = False
    ) -> None:
        self.n += 1
        self.adapters.tables.append(
            "eval_result",
            [
                {
                    "run_id": f"run{self.n}",
                    "ts": when,
                    "pack_id": pack_id,
                    "pack_version": 1,
                    "manifest_sha256": "0" * 64,
                    "dimension": "security",
                    "target_kind": "agent",
                    "target_id": agent_id,
                    "status": status,
                    "metrics": {},
                    "metric_status": {},
                    "thresholds": {},
                    "reasons": "",
                    "n_items": 1,
                    "data_mode": "synthetic",
                    "dataset_id": "d",
                    "dataset_sha256": "0" * 64,
                    "is_mock": mock,
                    "launch_gate": "none",
                    "judge_gate": False,
                    "details": {},
                }
            ],
        )

    def risk(self, title: str, agent: str, links: Sequence[tuple[str, str]] = (), **kw: Any) -> str:
        data = {
            "title": title,
            "category": "money_movement",
            "agent_id": agent,
            "inherent_likelihood": 4,
            "inherent_impact": 5,
            "residual_likelihood": 2,
            "residual_impact": 5,
            "treatment": "mitigate",
            "owner": "ops",
            "review_date": "2027-04-20",
            "status": "active",
        } | kw
        return self.svc.create(data, "harness", links=links)["risk_id"]

    def window_time(self, hours_before_end: int = 2) -> dt.datetime:
        w = ev.window_for(self.adapters.clock.now(), self.settings.risk_evidence_window_days)
        return w.end - dt.timedelta(hours=hours_before_end)


def _state_of(env: _Env, risk_id: str) -> dict[str, Any]:
    env.svc.run_evidence()
    return env.svc.get(risk_id)


def probes(env: _Env) -> list[tuple[str, Callable[[], bool]]]:
    th = Thresholds()
    chain = [("system", "a", "tool", "t0")] + [
        ("tool", f"t{i}", "tool", f"t{i + 1}") for i in range(3000)
    ]

    def levels(g: Graph, pts: list[inherit.RiskPoint]) -> dict[str, inherit.AgentRisk]:
        return inherit.compute(g, pts, th)

    def p_cycle() -> bool:
        g = _agent_graph(
            ("system", "a", "tool", "t1"),
            ("tool", "t1", "tool", "t2"),
            ("tool", "t2", "tool", "t1"),
        )
        return levels(g, [_pt("r", "tool", "t2", 20)])["a"].inherent_level == "critical"

    def p_self_loop() -> bool:
        g = _agent_graph(("system", "a", "tool", "t1"), ("tool", "t1", "tool", "t1"))
        return levels(g, [_pt("r", "tool", "t1", 12)])["a"].inherent_level == "high"

    def p_deep() -> bool:
        g = _agent_graph(*chain)
        return levels(g, [_pt("r", "tool", "t3000", 25)])["a"].inherent_level == "critical"

    def p_gone_node() -> bool:
        g = _agent_graph(("system", "a", "tool", "t1"))
        g.nodes[node_id_for("tool", "t1")].status = "gone"
        return levels(g, [_pt("r", "tool", "t1", 25)])["a"].inherent_level is None

    def p_retired_risk() -> bool:
        g = _agent_graph(("system", "a", "tool", "t1"))
        return levels(g, [_pt("r", "tool", "t1", 25, "retired")])["a"].inherent_level is None

    def p_draft_risk() -> bool:
        g = _agent_graph(("system", "a", "tool", "t1"))
        return levels(g, [_pt("r", "tool", "t1", 25, "draft")])["a"].inherent_level is None

    def p_conflict() -> bool:
        base = {
            "title": "Same risk", "category": "pii", "agent_id": "x", "inherent_likelihood": 3,
            "inherent_impact": 3, "owner": "o", "status": "draft",
        }  # fmt: skip
        docs = [
            {**base, "id": "C-1", "treatment": "mitigate", "links": []},
            {**base, "id": "C-2", "treatment": "avoid", "links": []},
        ]
        res = env.svc.import_docs(docs, "harness", dry_run=True)
        return any("conflicting treatments" in e for e in res.errors)

    def p_dup_id() -> bool:
        base = {
            "category": "pii", "agent_id": "x", "inherent_likelihood": 3, "inherent_impact": 3,
            "owner": "o", "status": "draft", "treatment": "mitigate", "links": [],
        }  # fmt: skip
        docs = [{**base, "id": "D-1", "title": "one"}, {**base, "id": "D-1", "title": "two"}]
        return any(
            "used twice" in e for e in env.svc.import_docs(docs, "harness", dry_run=True).errors
        )

    def p_accept_lowered() -> bool:
        return _expect_error(
            lambda: env.risk("acc", "z1", treatment="accept", treatment_note="ok",
                             residual_likelihood=1, residual_impact=1),
            "accept",
        )  # fmt: skip

    def p_accept_no_note() -> bool:
        return _expect_error(
            lambda: env.risk("acc2", "z2", treatment="accept", residual_likelihood=4,
                             residual_impact=5),
            "justification",
        )  # fmt: skip

    def p_shadow() -> bool:
        env.agent("sh1", "SHADOW")
        rid = env.risk("shadow evidence", "sh1", [("rule", "PAY-02")])
        env.verdict("sh1", "PAY-02", "block", env.window_time())
        r = _state_of(env, rid)
        return r["evidence_state"] == "no_evidence" and r["residual_score"] == 20

    def p_retired_agent() -> bool:
        env.agent("rt1", "RETIRED")
        rid = env.risk("retired agent evidence", "rt1", [("rule", "PAY-02")])
        env.verdict("rt1", "PAY-02", "block", env.window_time())
        r = _state_of(env, rid)
        return r["evidence_state"] == "no_evidence" and r["residual_score"] == 20

    def p_rule_removed() -> bool:
        env.agent("rm1")
        rid = env.risk("removed rule", "rm1", [("rule", "PAY-03")])
        env.rules.discard("PAY-03")
        try:
            env.verdict("rm1", "PAY-03", "block", env.window_time())
            r = _state_of(env, rid)
            return r["evidence_state"] == "failing" and r["residual_score"] == 20
        finally:
            env.rules.add("PAY-03")

    def p_mock_pack() -> bool:
        env.agent("mk1")
        rid = env.risk("mock pack", "mk1", [("pack", "pack_a")])
        env.pack("mk1", "pack_a", "ok", env.window_time(), mock=True)
        r = _state_of(env, rid)
        return r["evidence_state"] == "no_evidence" and r["residual_score"] == 20

    def p_pack_beats_rule() -> bool:
        env.agent("pf1")
        rid = env.risk("pack fails", "pf1", [("rule", "PAY-02"), ("pack", "pack_a")])
        env.verdict("pf1", "PAY-02", "block", env.window_time())
        env.pack("pf1", "pack_a", "fail", env.window_time())
        r = _state_of(env, rid)
        return r["evidence_state"] == "failing" and r["residual_score"] == 20

    def p_stale() -> bool:
        env.agent("st1")
        rid = env.risk("stale", "st1", [("rule", "PAY-02")])
        env.verdict("st1", "PAY-02", "block", env.window_time())
        env.svc.run_evidence()
        good = env.svc.get(rid)["residual_score"] == 10
        later = env.adapters.clock.now() + dt.timedelta(
            days=3 * env.settings.risk_evidence_window_days
        )
        row = env.svc._need(rid)  # noqa: SLF001
        latest = env.svc._latest_evidence(rid).get(rid)  # noqa: SLF001
        eff = env.svc.effective(row, latest, later)
        return good and eff["evidence_reason"] == "stale_evidence" and eff["residual_score"] == 20

    def p_residual_above() -> bool:
        return _expect_error(
            lambda: env.risk("up", "z3", residual_likelihood=5, residual_impact=5),
            "cannot be above",
        )

    def p_types() -> bool:
        bad = (True, "3", 3.0, 0, 6, None)
        return all(
            _expect_error(lambda v=v: env.risk("t", "z4", inherent_likelihood=v)) for v in bad
        )

    def p_bad_ids() -> bool:
        rid = env.risk("ok", "z5")
        bad_ids = ["../x", "RSK-1; DROP TABLE risk", "a" * 200, "", "a b"]
        errors = all(_expect_error(lambda v=v: env.svc.get(v)) for v in bad_ids)
        links = all(
            _expect_error(lambda v=v: env.svc.add_link(rid, "rule", v, "h"))
            for v in ("PAY-02'; --", "x" * 200, "")
        )
        return (
            errors
            and links
            and _expect_error(lambda: env.svc.add_link(rid, "rule", "PAY-777", "h"))
        )

    def p_csv() -> bool:
        env.risk('=HYPERLINK("http://x")', "z6", owner="+cmd")
        text, _ = env.svc.export_csv()
        return "'=HYPERLINK" in text and "'+cmd" in text and ",=HYPERLINK" not in text

    return [
        ("cycle_in_graph", p_cycle),
        ("self_loop_edge", p_self_loop),
        ("chain_3000_deep", p_deep),
        ("retired_node_passes_nothing", p_gone_node),
        ("retired_risk_ignored", p_retired_risk),
        ("draft_risk_ignored", p_draft_risk),
        ("conflicting_treatments_refused", p_conflict),
        ("duplicate_id_in_import_refused", p_dup_id),
        ("accept_with_lowered_residual_refused", p_accept_lowered),
        ("accept_without_justification_refused", p_accept_no_note),
        ("shadow_agent_evidence_not_counted", p_shadow),
        ("retired_agent_evidence_not_counted", p_retired_agent),
        ("rule_removed_from_policy_is_failing", p_rule_removed),
        ("mock_pack_result_not_counted", p_mock_pack),
        ("failed_pack_beats_rule_hits", p_pack_beats_rule),
        ("stale_evidence_raises_residual", p_stale),
        ("residual_above_inherent_refused", p_residual_above),
        ("type_confusion_refused", p_types),
        ("bad_ids_and_link_targets_refused", p_bad_ids),
        ("csv_formula_injection_neutralised", p_csv),
    ]


def run_adversarial() -> dict[str, Any]:
    env = _Env()
    results: dict[str, bool] = {}
    try:
        for name, fn in probes(env):
            try:
                results[name] = bool(fn())
            except Exception as exc:  # noqa: BLE001 - a crash is a failed probe, reported by name
                results[name] = False
                results[f"{name}__error"] = False
                print(f"[probe {name}] {type(exc).__name__}: {exc}"[:300])  # noqa: T201
    finally:
        env.close()
    named = {k: v for k, v in results.items() if not k.endswith("__error")}
    k = sum(1 for v in named.values() if v)
    return {
        "n": len(named),
        "passed": k,
        "bp": _bp(k, len(named)),
        "ci_bp": list(wilson_bp(k, len(named))),
        "failed": sorted(n for n, v in named.items() if not v),
        "probes": named,
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
    ap = argparse.ArgumentParser(prog="python -m supervisor.risk.harness", description=__doc__)
    ap.add_argument("--split", choices=("dev", "held_out", "both"), default="both")
    ap.add_argument("--fixtures", help="fixture folder (default: tests/fixtures/risk)")
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
    print(f"[starters] risks={st['risks']} links={st['links']} problems={st['problems']}")  # noqa: T201
    print(f"[determinism] {res['determinism']['bp']}bp")  # noqa: T201
    bad = 0
    for name, v in res["verdicts"].items():
        print(f"    {name}: {v}")  # noqa: T201
        bad += v != "GO"
    if args.write_baseline:
        (fixtures / "baseline.json").write_text(
            json.dumps(
                {
                    "note": "Recorded by `python -m supervisor.risk.harness --write-baseline`. "
                    "tests/risk/test_harness.py fails if a metric drops below this.",
                    "date": dt.date.today().isoformat(),
                    "base_commit": BASE_COMMIT,
                    "branch": "wp29-risk-register",
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
        "starters": {k: res["starters"][k] for k in ("risks", "links", "bp")},
        "adversarial": {k: res["adversarial"][k] for k in ("n", "passed", "bp")},
        "verdicts": res["verdicts"],
    }


if __name__ == "__main__":
    sys.exit(main())

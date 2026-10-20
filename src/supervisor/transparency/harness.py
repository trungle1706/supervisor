"""Evaluation harness for the transparency report (WP31; TEAM_BRIEF section 3 adapted to a
document product).

    python -m supervisor.transparency.harness [--split dev|held_out|both] [--fixtures DIR]
                                              [--write-baseline]

A report has no AI part: every field is read from a store or a settings flag and every word
comes from a table. So there is no model, no mock path to label and no model card; what can go
wrong is a wrong section, a wrong gap statement, a leak to the wrong audience or a changing
hash. The harness measures those, with no model and no network:

1. The golden set, ``tests/fixtures/transparency/golden.jsonl``: 54 synthetic scenarios (36 dev,
   18 held-out), each (demo agent, variant, profile). A profile sets the facts: everything on,
   risk register off, inventory off, a chain check that fails, one that passes, two open cases.
   The fixture workspace is the three demo agents' manifests plus the WP24 workspace fixture
   ``tests/fixtures/inventory/workspace_7.json``. Expected values come from an independent
   reference (``tests/fixtures/transparency/generate.py``). Never tune on the held-out split.
2. Determinism: the same facts give the same content hash, and the same JSON bytes under a fixed
   clock.
3. Adversarial probes: 22 cases the golden set does not generate (personal data planted in a
   case title, a retired agent, an agent with no inventory node, half the sources off, a failed
   chain check, a removed obligation, oversized lists, a Vietnamese name in a model card, a
   stale previous version, an allow-list that leaks to customers, markup in a name, a collector
   that fails or returns a float, a PDF with no font, a file that already exists...). Reported
   as a separate row; a report that passes only its own scenarios is NO-GO.

Expert rubrics (docs/transparency-report.md): "regulator inspector (SBV)" and "data protection
officer". Numbers are integers (basis points, counts) with Wilson 95 percent intervals.
GO / NO-GO thresholds are ILLUSTRATIVE; the bank sets its own.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import re
import sys
import tempfile
from collections import Counter
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import Any

from supervisor.transparency import allowlist, render
from supervisor.transparency.model import SECTIONS, VARIANTS, TransparencyError

THRESHOLDS_BP = {"golden": 10000, "adversarial": 10000, "determinism": 10000, "leaks_max": 0}
Z95 = 1.959964
BASE_COMMIT = "316a039"
AGENT_IDS = ("customer_service", "credit_prequal", "payments")
PROFILES = ("base", "risk_off", "inventory_off", "chain_fail", "verified", "cases2")


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

    return REPO_ROOT / "tests" / "fixtures" / "transparency"


def load_golden(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]


class FixedClock:
    """A clock that does not move (determinism runs)."""

    def __init__(self, inner: Any) -> None:
        self._t = inner.now()

    def now(self) -> Any:
        return self._t


# ----------------------------------------------------------------------------- environment


class Env:
    """A temporary SQLite store with the three demo agents, their inventory (manifests plus the
    workspace fixture), the starter risks, a real chain writer and a TransparencyService."""

    def __init__(self) -> None:
        from supervisor.adapters.factory import build_adapters
        from supervisor.adapters.workspace.fixtures import FixtureWorkspaceReader
        from supervisor.config import REPO_ROOT, load_settings
        from supervisor.inventory.service import InventoryService
        from supervisor.risk.service import RiskService
        from supervisor.transparency.service import TransparencyService
        from supervisor.wiring import build_runtime, register_agents
        from supervisor_agents.common.manifest import load_manifest

        self._tmp = tempfile.TemporaryDirectory()
        self.settings = load_settings(
            sql_backend="sqlite",
            data_dir=Path(self._tmp.name) / "data",
            llm_base_url="",
            inventory_enabled=True,
            risk_register_enabled=True,
            transparency_enabled=True,
        )
        self.adapters = build_adapters(self.settings)
        self.rt = build_runtime(self.settings, adapters=self.adapters, policy_refresh_s=0.0)
        register_agents(self.rt, [load_manifest(a) for a in AGENT_IDS])
        inv = InventoryService.from_adapters(self.adapters)
        inv.fill_manifests()
        inv.refresh_workspace(
            FixtureWorkspaceReader.from_file(
                REPO_ROOT / "tests" / "fixtures" / "inventory" / "workspace_7.json"
            )
        )
        risks = RiskService(
            self.adapters.state,
            self.adapters.tables,
            self.adapters.clock,
            self.settings,
            evidence=self.rt.chain,
        )
        res = risks.import_path(REPO_ROOT / "config" / "risks", "harness", source="starter")
        assert not res.errors, res.errors
        self.rt.chain.commit_root(force=True)
        self.svc = TransparencyService.from_adapters(self.adapters, evidence=self.rt.chain)
        self.n = 0

    def close(self) -> None:
        try:
            self.rt.close()
        finally:
            self.adapters.close()
            self._tmp.cleanup()

    # -- fact helpers
    def agent_row(self, agent_id: str) -> dict[str, Any]:
        return dict(self.adapters.state.get("agent", {"agent_id": agent_id}))

    def add_agent(self, agent_id: str, **over: Any) -> None:
        row = {
            "agent_id": agent_id,
            "name": over.pop("name", agent_id),
            "owner_team": "Team Probe",
            "owner_user": "probe.owner@example.invalid",
            "risk_tier": "high",
            "host_type": "python_inprocess",
            "plug_point": "gate_hook",
            "model_family": "qwen",
            "status": "active",
            "gate_state": "RUNNING",
            "created_at": self.adapters.clock.now(),
        } | over
        self.adapters.state.insert("agent", row)
        self.rt.chain.record(
            "agent_registered", agent_id, {"agent_id": agent_id, "ts": "2026-10-20T00:00:00Z"}
        )

    def add_case(self, agent_id: str, summary: str, severity: str = "medium") -> str:
        from supervisor.core.models import Case

        self.n += 1
        case = Case(
            case_id=f"C-HRN-{self.n:04d}",
            agent_id=agent_id,
            severity=severity,
            opened_at=self.adapters.clock.now(),
            summary=summary,
            regulation_refs=[],
        )
        row = case.row()
        row.pop("row_version")
        row.pop("updated_at")
        self.adapters.state.insert("cases", row)
        return str(case.case_id)

    def add_eval(
        self, agent_id: str, pack_id: str, *, status: str = "ok", mock: bool = False
    ) -> None:
        self.n += 1
        self.adapters.tables.append(
            "eval_result",
            [
                {
                    "run_id": f"run-hrn-{self.n}",
                    "ts": self.adapters.clock.now(),
                    "pack_id": pack_id,
                    "pack_version": 1,
                    "manifest_sha256": "a" * 64,
                    "dimension": "privacy",
                    "target_kind": "agent",
                    "target_id": agent_id,
                    "status": status,
                    "metrics": {"leak_bp": 0},
                    "metric_status": {"leak_bp": "ok"},
                    "thresholds": {},
                    "reasons": "",
                    "n_items": 5,
                    "data_mode": "synthetic",
                    "dataset_id": "d1",
                    "dataset_sha256": "b" * 64,
                    "is_mock": mock,
                    "launch_gate": "required",
                    "judge_gate": False,
                    "details": {},
                }
            ],
        )

    def set_verify(self, ok: bool | None) -> None:
        self.svc.src.verify_fn = (
            None if ok is None else (lambda lane: {"ok": ok, "failures": 0 if ok else 2})
        )

    def texts(self, report: dict[str, Any]) -> str:
        """JSON, Vietnamese text and English text of a report in one string."""
        return "\n".join(
            [
                render.render_json(report).decode("utf-8"),
                render.plain_text(report, "vi"),
                render.plain_text(report, "en"),
            ]
        )


def has_word(text: str, word: str) -> bool:
    """The word as a whole identifier (``payments`` is not found in ``executes_payments``)."""
    return bool(
        re.search(rf"(?<![A-Za-z0-9_]){re.escape(word.lower())}(?![A-Za-z0-9_])", text.lower())
    )


# ----------------------------------------------------------------------------- golden items


def _apply_profile(env: Env, profile: str) -> Callable[[], None]:
    """Set the facts of a profile; returns the function that undoes it."""
    s = env.settings
    undo: Callable[[], None] = lambda: None  # noqa: E731
    if profile == "risk_off":
        s.risk_register_enabled = False
        undo = lambda: setattr(s, "risk_register_enabled", True)  # noqa: E731
    elif profile == "inventory_off":
        s.inventory_enabled = False
        undo = lambda: setattr(s, "inventory_enabled", True)  # noqa: E731
    elif profile == "chain_fail":
        env.set_verify(False)
        undo = lambda: env.set_verify(None)  # noqa: E731
    return undo


def check_item(env: Env, item: dict[str, Any], report: dict[str, Any]) -> dict[str, str]:
    """Problems of one scenario by kind (empty = pass)."""
    exp, agent, variant = item["expected"], item["agent"], item["variant"]
    row = env.agent_row(agent)
    subst = {
        "{agent_id}": agent,
        "{owner_user}": str(row["owner_user"]),
        "{owner_team}": str(row["owner_team"]),
    }
    secs = report["sections"]
    out: dict[str, str] = {}
    got = {sid: bool(secs[sid]["available"]) for sid in SECTIONS if sid in secs}
    if got != exp["avail"]:
        out["availability"] = ",".join(
            sorted(s for s in exp["avail"] if got.get(s) != exp["avail"][s])
        )
    cls = (secs["classification"].get("data") or {}).get("decision33_class")
    if cls != exp["d33_class"]:
        out["classification"] = f"{cls}"
    ver = ((secs["evidence"].get("data") or {}).get("verify") or {}).get("state")
    if ver != exp["verify_state"]:
        out["verify_state"] = f"{ver}"
    if exp["open_cases"] is not None:
        n = (secs["cases"].get("data") or {}).get("open_n")
        if n != exp["open_cases"]:
            out["cases"] = f"{n}"
    if exp["d33_ids_cited"] is not None:
        n = len((secs["classification"].get("data") or {}).get("d33_obligation_ids") or [])
        if n != exp["d33_ids_cited"]:
            out["obligation_ids"] = f"{n}"
    codes = {i["code"] for i in (secs["not_shown"].get("data") or {}).get("items") or []}
    miss = sorted(set(exp["not_shown_has"]) - codes)
    extra = sorted(set(exp["not_shown_lacks"]) & codes)
    if miss or extra:
        out["not_shown"] = f"missing={miss} unexpected={extra}"
    text = env.texts(report)
    for w in exp["text_has"]:
        if subst.get(w, w).lower() not in text.lower():
            out["text_has"] = w
    for w in exp["text_lacks"]:
        if has_word(text, subst.get(w, w)):
            out["leak" if variant == "customer" else "text_lacks"] = w
    return out


def run_golden(items: list[dict[str, Any]], split: str | None = None) -> dict[str, Any]:
    chosen = [i for i in items if split in (None, "both") or i["split"] == split]
    by_key = {(i["agent"], i["profile"], i["variant"]): i for i in chosen}
    results: dict[str, dict[str, str]] = {}
    for agent in sorted({i["agent"] for i in chosen}):
        env = Env()
        try:
            for profile in PROFILES:
                undo = _apply_profile(env, profile)
                try:
                    if profile == "cases2":
                        env.add_case(agent, "Test case one", "critical")
                        env.add_case(agent, "Test case two", "low")
                    for variant in VARIANTS:
                        item = by_key.get((agent, profile, variant))
                        if item is None:
                            continue
                        report = env.svc.preview(
                            agent, variant, fresh_verify=profile in ("chain_fail", "verified")
                        )
                        results[item["id"]] = check_item(env, item, report)
                finally:
                    undo()
        finally:
            env.close()
    n = len(chosen)
    correct = sum(1 for i in chosen if not results.get(i["id"], {"missing": "x"}))
    kinds = Counter(k for r in results.values() for k in r)
    by_variant: dict[str, dict[str, int]] = {}
    for i in chosen:
        d = by_variant.setdefault(i["variant"], {"n": 0, "correct": 0})
        d["n"] += 1
        d["correct"] += 0 if results.get(i["id"]) else 1
    return {
        "n": n,
        "correct": correct,
        "accuracy_bp": _bp(correct, n),
        "accuracy_ci_bp": list(wilson_bp(correct, n)),
        "by_variant": {
            v: {**d, "bp": _bp(d["correct"], d["n"])} for v, d in sorted(by_variant.items())
        },
        "leaks": kinds.get("leak", 0),
        "failure_taxonomy": {
            "by_kind": dict(sorted(kinds.items())),
            "misses": [
                {"id": i["id"], "problems": results[i["id"]]}
                for i in chosen
                if results.get(i["id"])
            ],
        },
        "result_hash": hashlib.sha256(
            json.dumps(sorted(results.items()), sort_keys=True).encode()
        ).hexdigest(),
    }


# ----------------------------------------------------------------------------- determinism


def run_determinism() -> dict[str, Any]:
    """Same facts, same content hash (any clock); same JSON bytes under a fixed clock."""
    from supervisor.transparency.builder import content_hash

    env = Env()
    try:
        ok_content = ok_json = True
        for variant in VARIANTS:
            a = env.svc.preview("payments", variant)
            b = env.svc.preview("payments", variant)
            ok_content &= content_hash(a) == content_hash(b)
        env.svc.src.clock = FixedClock(env.svc.src.clock)
        for variant in VARIANTS:
            a = env.svc.preview("payments", variant)
            b = env.svc.preview("payments", variant)
            ok_json &= render.render_json(a) == render.render_json(b)
            ok_json &= render.render_html(a, "vi") == render.render_html(b, "vi")
    finally:
        env.close()
    return {"bp": 10000 if ok_content and ok_json else 0, "content": ok_content, "json": ok_json}


# ----------------------------------------------------------------------------- probes

PII_TITLE = "Khach Nguyen Van An, SDT 0912345678, CCCD 001201001234 bi chan"


def probes(env: Env) -> list[tuple[str, Callable[[], bool]]]:
    from supervisor.transparency import builder as B
    from supervisor.transparency.builder import Ctx, ReportBuilder, na, ok
    from supervisor.transparency.model import UnknownAgent, assert_plain

    svc = env.svc

    def build(agent: str, variant: str, **kw: Any) -> dict[str, Any]:
        return svc.preview(agent, variant, **kw)

    def codes(report: dict[str, Any]) -> set[str]:
        return {i["code"] for i in report["sections"]["not_shown"]["data"]["items"]}

    def p_pii_title() -> bool:
        env.add_agent("probe_pii")
        env.add_case("probe_pii", PII_TITLE)
        internal = env.texts(build("probe_pii", "internal"))
        reg = env.texts(build("probe_pii", "regulator"))
        cust = env.texts(build("probe_pii", "customer"))
        raw = ("0912345678", "001201001234")
        masked_in_internal = "Test" not in internal and all(r not in internal for r in raw)
        no_text_elsewhere = all(r not in reg and r not in cust for r in raw)
        shown = '"summary"' in internal  # the internal variant does list a (masked) title
        return masked_in_internal and no_text_elsewhere and shown

    def p_retired() -> bool:
        env.add_agent("probe_retired", status="retired", gate_state="QUARANTINED")
        r = build("probe_retired", "regulator")
        return "agent_retired" in codes(r) and r["sections"]["identity"]["available"]

    def p_no_inventory_node() -> bool:
        env.add_agent("probe_ghost")
        r = build("probe_ghost", "regulator")
        s = r["sections"]
        return (
            s["inventory"]["reason"] == "not_in_inventory"
            and s["compliance"]["reason"] == "no_matrix"
            and "section_not_in_inventory" in codes(r)
            and s["identity"]["available"]
        )

    def p_half_flags_off() -> bool:
        st = env.settings
        st.risk_register_enabled = st.inventory_enabled = False
        try:
            reg = build("payments", "regulator")
            cust = build("payments", "customer")
        finally:
            st.risk_register_enabled = st.inventory_enabled = True
        refs = {reg["sections"]["risks"]["ref"], reg["sections"]["inventory"]["ref"]}
        return (
            refs == {"RISK_REGISTER_ENABLED", "INVENTORY_ENABLED"}
            and cust["sections"]["risks"]["ref"] is None  # a flag name is internal
            and "RISK_REGISTER_ENABLED" not in env.texts(cust)
        )

    def p_chain_fail_stated() -> bool:
        env.set_verify(False)
        try:
            reg = build("payments", "regulator", fresh_verify=True)
            cust = build("payments", "customer", fresh_verify=True)
        finally:
            env.set_verify(None)
        return (
            "chain_verify_failed" in codes(reg)
            and "chain_verify_failed" in codes(cust)
            and "KHÔNG ĐẠT" in render.plain_text(reg, "vi")
            and "did not pass" in render.plain_text(cust, "en")
        )

    def p_obligation_removed() -> bool:
        real = svc.facts.matrix

        def cut(agent: str) -> dict[str, Any]:
            m = dict(real(agent))
            m["rows"] = [r for r in m["rows"] if not r["obligation_id"].endswith("PL4.1-01")]
            return m

        svc.facts.matrix = cut  # type: ignore[method-assign]
        try:
            r = build("payments", "regulator")
        finally:
            svc.facts.matrix = real  # type: ignore[method-assign]
        data = r["sections"]["compliance"]["data"]
        return (
            "VN-QD33-2026-PL4.1-01" in data["d33_ids_missing"]
            and "obligation_missing" in codes(r)
            and "VN-QD33-2026-PL4.1-01" in render.plain_text(r, "en")
        )

    def p_oversized() -> bool:
        env.add_agent("probe_big")
        for i in range(120):
            env.add_case("probe_big", f"Case number {i}")
            env.add_eval("probe_big", f"pack_{i:03d}")
        r = build("probe_big", "internal")
        cases, assur = r["sections"]["cases"]["data"], r["sections"]["assurance"]["data"]
        from supervisor.transparency.model import MAX_ROWS

        return (
            len(cases["items"]) == MAX_ROWS
            and cases["more"] == 120 - MAX_ROWS
            and len(assur["packs"]) == MAX_ROWS
            and assur["more"] == 120 - MAX_ROWS
            and "truncated" in codes(r)
            and len(render.render_json(r)) < 400_000
        )

    def p_vietnamese_name() -> bool:
        name = "Nguyễn Văn Ánh"
        env.settings.mrm_model_owner = name
        try:
            reg = env.texts(build("payments", "regulator"))
            cust = env.texts(build("payments", "customer"))
            internal = env.texts(build("payments", "internal"))
        finally:
            env.settings.mrm_model_owner = "FILL-ME-model-owner"
        # the masker may or may not catch the name in the internal text; the two outer variants
        # must not carry it either way
        return name not in reg and name not in cust and bool(internal)

    def p_stale_previous_version() -> bool:
        env.add_agent("probe_stale")
        first = svc.generate("probe_stale", ("regulator",), actor="probe", fresh_verify=False)[0]
        again = svc.generate("probe_stale", ("regulator",), actor="probe", fresh_verify=False)[0]
        env.add_case("probe_stale", "A new case changes the facts")
        second = svc.generate("probe_stale", ("regulator",), actor="probe", fresh_verify=False)[0]
        rows = svc.rows("probe_stale", "regulator")
        return (
            first["version"] == 1
            and again["status"] == "unchanged"
            and second["version"] == 2
            and "cases" in second["diff"]["changed"]
            and {r["version"] for r in rows} == {1, 2}  # the old version stays (append-only)
            and svc.latest("probe_stale", "regulator")["version"] == 2
        )

    def p_bad_allowlist_customer() -> bool:
        saved = allowlist.CUSTOMER["identity"]
        allowlist.set_spec("customer", "identity", {"kind": True, "owner_user": True})
        try:
            build("payments", "customer")
            leaked = False
        except TransparencyError:
            leaked = True
        finally:
            allowlist.SPECS["customer"]["identity"] = saved
        allowlist.set_spec("customer", "evidence", {"lane": True, "verify": {"state": True}})
        try:
            build("payments", "customer")
            leaked2 = False
        except TransparencyError:
            leaked2 = True
        finally:
            allowlist.SPECS["customer"].pop("evidence", None)
            allowlist.set_spec("customer", "evidence", {"verify": {"state": True}})
        return leaked and leaked2

    def p_customer_clean() -> bool:
        ok_all = True
        for agent in AGENT_IDS:
            r = build(agent, "customer")
            text = env.texts(r)
            row = env.agent_row(agent)
            ok_all &= not any(has_word(text, a) for a in AGENT_IDS)
            ok_all &= str(row["owner_user"]).lower() not in text.lower()
            ok_all &= not re.search(r"\b[0-9a-f]{32,}\b", text)
            ok_all &= not re.search(r"\b(?!SHA)[A-Z]{2,6}-\d{2,3}\b", text)
            ok_all &= "VN-" not in text and "INTL-" not in text
            ok_all &= "agent_id" not in r
        return ok_all

    def p_content_hash_stable() -> bool:
        from supervisor.transparency.builder import content_hash

        a, b = build("credit_prequal", "regulator"), build("credit_prequal", "regulator")
        return content_hash(a) == content_hash(b)

    def p_forced_new_version() -> bool:
        env.add_agent("probe_force")
        one = svc.generate("probe_force", ("customer",), actor="probe", fresh_verify=False)[0]
        two = svc.generate(
            "probe_force", ("customer",), actor="probe", force=True, fresh_verify=False
        )[0]
        return (
            one["version"] == 1
            and two["version"] == 2
            and one["content_hash"] == two["content_hash"]
        )

    def p_actor_never_printed() -> bool:
        from supervisor.risk.service import RiskService

        env.add_agent("probe_actor")
        actor = "someone.private@example.invalid"
        RiskService(
            env.adapters.state,
            env.adapters.tables,
            env.adapters.clock,
            env.settings,
            evidence=env.rt.chain,
        ).create(
            {
                "title": "Probe risk",
                "category": "pii",
                "agent_id": "probe_actor",
                "inherent_likelihood": 3,
                "inherent_impact": 3,
                "residual_likelihood": 2,
                "residual_impact": 2,
                "treatment": "mitigate",
                "review_date": "2027-04-20",
                "owner": "Probe Team",
                "status": "active",
            },
            actor,
        )
        return all(
            actor not in env.texts(build("probe_actor", v)) for v in ("regulator", "customer")
        ) and '"actor"' not in env.texts(build("probe_actor", "regulator"))

    def p_float_refused() -> bool:
        b = ReportBuilder(svc.facts)
        b.register("controls", lambda c: ok({"score": 0.5}))
        allowlist.set_spec("internal", "controls", True)
        try:
            b.build("payments", "internal")
            return False
        except TransparencyError:
            return True

    def p_collector_error() -> bool:
        b = ReportBuilder(svc.facts)

        def boom(_c: Ctx) -> dict[str, Any]:
            raise RuntimeError("source down: secret detail")

        b.register("masking", boom)
        r = b.build("payments", "regulator")
        s = r["sections"]["masking"]
        text = render.plain_text(r, "en") + json.dumps(r)
        return (
            not s["available"]
            and s["reason"] == "source_error"
            and "section_source_error"
            in {i["code"] for i in r["sections"]["not_shown"]["data"]["items"]}
            and "secret detail" not in text  # the message is not copied, only the class name
        )

    def p_unknown_and_bad_ids() -> bool:
        results = []
        for bad in ("no_such_agent", "../etc/passwd", "a b", "x" * 80, ""):
            try:
                build(bad, "regulator")
                results.append(False)
            except (UnknownAgent, TransparencyError):
                results.append(True)
        try:
            build("payments", "everyone")
            results.append(False)
        except TransparencyError:
            results.append(True)
        return all(results)

    def p_pdf_no_font_falls_back() -> bool:
        import importlib

        rp = importlib.import_module("supervisor.evidence.casefile.render_pdf")

        saved = rp.FONT_CANDIDATES
        rp.FONT_CANDIDATES = ()
        try:
            res = render.render_pdf(build("payments", "customer"), "vi", font_path=None)
        finally:
            rp.FONT_CANDIDATES = saved
        return res.fmt == "html" and bool(res.notice) and res.data.startswith(b"<!DOCTYPE html>")

    def p_pdf_offline() -> bool:
        import socket

        try:
            import fpdf  # noqa: F401
        except ImportError:
            return True  # nothing to render: the fallback probe covers this install
        real = socket.socket.connect

        def refuse(*_a: Any, **_k: Any) -> None:
            raise OSError("network is off in this probe")

        socket.socket.connect = refuse  # type: ignore[method-assign,assignment]
        try:
            res = render.render_pdf(build("payments", "regulator"), "vi")
        finally:
            socket.socket.connect = real  # type: ignore[method-assign]
        return res.fmt == "pdf" and res.data.startswith(b"%PDF")

    def p_markup_escaped() -> bool:
        env.add_agent("probe_xss", name="<script>alert(1)</script> & co")
        html = render.render_html(build("probe_xss", "regulator"), "en").decode("utf-8")
        return "<script>alert(1)" not in html and "&lt;script&gt;" in html

    def p_hook_section() -> bool:
        b = ReportBuilder(svc.facts)
        b.register("controls", lambda c: ok({"controls_n": 3, "tasks_open": 2}))
        reg = b.build("payments", "regulator")
        internal = b.build("payments", "internal")
        allowlist.set_spec("regulator", "controls", {"controls_n": True})
        try:
            reg2 = b.build("payments", "regulator")
        finally:
            allowlist.set_spec("regulator", "controls", {})
        return (
            reg["sections"]["controls"]["data"] == {}  # no spec yet: nothing is copied
            and internal["sections"]["controls"]["data"]["tasks_open"] == 2
            and reg2["sections"]["controls"]["data"] == {"controls_n": 3}
        )

    def p_mock_results_labelled() -> bool:
        env.add_agent("probe_mock")
        env.add_eval("probe_mock", "pii_canary", mock=True)
        r = build("probe_mock", "regulator")
        return (
            "mock_results" in codes(r)
            and r["sections"]["assurance"]["data"]["mock_n"] == 1
            and "mock_judge" in codes(r)
        )

    def p_no_overwrite() -> bool:
        env.add_agent("probe_over")
        folder = svc._dir("probe_over", "regulator", 1)
        folder.mkdir(parents=True)
        (folder / "report.json").write_bytes(b"{}")
        try:
            svc.generate("probe_over", ("regulator",), actor="probe", fresh_verify=False)
            return False
        except TransparencyError:
            return not svc.rows("probe_over")  # no row was written for a refused version

    def p_long_text_cut() -> bool:
        env.add_agent("probe_long", name="N" * 500)
        env.add_case("probe_long", "word " * 400)
        r = build("probe_long", "internal")
        name = r["sections"]["identity"]["data"]["display_name"]
        summ = r["sections"]["cases"]["data"]["items"][0]["summary"]
        return len(name) <= 80 and len(summ) <= 120

    assert B  # the module is imported for the collectors used above
    assert assert_plain and na
    return [
        ("pii_planted_in_case_title_is_masked", p_pii_title),
        ("retired_agent_is_stated", p_retired),
        ("agent_without_inventory_node", p_no_inventory_node),
        ("half_the_sources_off_names_the_flags", p_half_flags_off),
        ("failed_chain_check_is_stated_to_all", p_chain_fail_stated),
        ("obligation_removed_from_the_matrix", p_obligation_removed),
        ("oversized_sections_are_cut_and_counted", p_oversized),
        ("vietnamese_name_in_model_card_internal_only", p_vietnamese_name),
        ("stale_previous_version_and_append_only", p_stale_previous_version),
        ("bad_customer_allowlist_is_refused", p_bad_allowlist_customer),
        ("customer_has_no_ids_hashes_rules_names", p_customer_clean),
        ("same_facts_same_content_hash", p_content_hash_stable),
        ("forced_run_adds_a_version_with_equal_content", p_forced_new_version),
        ("risk_actor_is_never_printed", p_actor_never_printed),
        ("a_float_is_refused", p_float_refused),
        ("a_failing_collector_degrades_the_section", p_collector_error),
        ("unknown_and_malformed_ids_and_variants", p_unknown_and_bad_ids),
        ("pdf_without_a_font_falls_back_to_html", p_pdf_no_font_falls_back),
        ("pdf_renders_with_the_network_refused", p_pdf_offline),
        ("markup_in_a_name_is_escaped", p_markup_escaped),
        ("hook_section_needs_an_allowlist_entry", p_hook_section),
        ("mock_results_are_labelled", p_mock_results_labelled),
        ("an_existing_file_is_never_overwritten", p_no_overwrite),
        ("long_text_is_cut", p_long_text_cut),
    ]


def run_adversarial() -> dict[str, Any]:
    env = Env()
    results: dict[str, bool] = {}
    try:
        for name, fn in probes(env):
            try:
                results[name] = bool(fn())
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
    out["determinism"] = run_determinism()
    out["adversarial"] = run_adversarial()
    verdicts = {}
    for s in splits:
        verdicts[f"golden_{s}"] = (
            "GO" if out["golden"][s]["accuracy_bp"] >= THRESHOLDS_BP["golden"] else "NO-GO"
        )
        verdicts[f"leaks_{s}"] = (
            "GO" if out["golden"][s]["leaks"] <= THRESHOLDS_BP["leaks_max"] else "NO-GO"
        )
    verdicts["determinism"] = (
        "GO" if out["determinism"]["bp"] >= THRESHOLDS_BP["determinism"] else "NO-GO"
    )
    verdicts["adversarial"] = (
        "GO" if out["adversarial"]["bp"] >= THRESHOLDS_BP["adversarial"] else "NO-GO"
    )
    out["verdicts"] = verdicts
    out["thresholds_bp"] = THRESHOLDS_BP
    out["thresholds_note"] = "ILLUSTRATIVE until the bank sets them"
    return out


def _print(res: dict[str, Any]) -> None:
    for s, g in res["golden"].items():
        lo, hi = g["accuracy_ci_bp"]
        print(  # noqa: T201
            f"[{s}] n={g['n']} accuracy={g['accuracy_bp']}bp [{lo}, {hi}] leaks={g['leaks']} "
            f"taxonomy={g['failure_taxonomy']['by_kind']}"
        )
    a = res["adversarial"]
    print(f"[adversarial] {a['passed']}/{a['n']} {a['ci_bp']} failed={a['failed']}")  # noqa: T201
    print(f"[determinism] {res['determinism']['bp']}bp")  # noqa: T201
    bad = [k for k, v in res["verdicts"].items() if v != "GO"]
    print("[OK] all GO" if not bad else f"[FAIL] NO-GO: {', '.join(bad)}")  # noqa: T201


def main(argv: Sequence[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        prog="python -m supervisor.transparency.harness", description=__doc__
    )
    ap.add_argument("--split", choices=("dev", "held_out", "both"), default="both")
    ap.add_argument("--fixtures", help="fixture folder (default: tests/fixtures/transparency)")
    ap.add_argument("--write-baseline", action="store_true")
    args = ap.parse_args(argv)
    fixtures = Path(args.fixtures) if args.fixtures else default_fixtures()
    splits = ("dev", "held_out") if args.split == "both" else (args.split,)
    res = run_all(fixtures, splits)
    _print(res)
    if args.write_baseline:
        import datetime as dt

        base = {
            "base_commit": BASE_COMMIT,
            "branch": "wp31-transparency",
            "date": dt.date.today().isoformat(),
            "note": "Recorded by `python -m supervisor.transparency.harness --write-baseline`. "
            "tests/transparency/test_harness.py fails if a metric drops below this.",
            "results": {
                "golden": {
                    s: {
                        k: g[k]
                        for k in ("n", "correct", "accuracy_bp", "accuracy_ci_bp", "result_hash")
                    }
                    | {"by_variant": g["by_variant"]}
                    for s, g in res["golden"].items()
                },
                "adversarial": {k: res["adversarial"][k] for k in ("n", "passed", "bp")},
                "determinism_bp": res["determinism"]["bp"],
            },
        }
        (fixtures / "baseline.json").write_text(
            json.dumps(base, indent=2, sort_keys=True) + "\n", encoding="utf-8", newline="\n"
        )
        print(f"[OK] wrote {fixtures / 'baseline.json'}")  # noqa: T201
    return 0 if all(v == "GO" for v in res["verdicts"].values()) else 1


if __name__ == "__main__":
    sys.exit(main())

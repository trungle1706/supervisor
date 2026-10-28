"""A fixture-replay model for development and tests of the test gate (WP-F5). NOT a product path.

``python -m supervisor.factory gate <agent> --kind full --model fake`` runs the real harness, the
real verifier and the real gate arithmetic, but the model that answers is this class. It does not
read the sources like a model would: it looks up the golden case of the run (by ``system_id``) and
replays the case's expected verdict, citing the case's expected evidence refs. As judge it
compares the expected and the actual verdicts, and as calibration judge it returns the expected
verdict of the case behind the sources it is shown.

So the numbers of such a run prove the plumbing (schema, evidence, tool scope, budgets, the six
harness tests, the signed report, the calibration arithmetic). They say nothing about how well an
agent or a judge reads a bank document. Only a run on the gateway model does that.

The CLI refuses ``--model fake`` when ``SUPERVISOR_MODE=databricks_app``. The class sets
``is_mock = False`` because the runtime refuses a mock; ``model_id`` says what it is.
"""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from typing import Any

FAKE_REFUSED_TEXT = (
    "--model fake is for development and tests only and is refused in databricks_app mode; "
    "run the gate on the gateway model (LLM_BASE_URL)"
)
MODEL_ID = "dev-fixture-replay"


def refused(settings: Any) -> bool:
    return getattr(settings, "supervisor_mode", "") == "databricks_app"


def _quote(text: str) -> str:
    return " ".join(str(text).split())[:30]


def _refs_of(inputs: Mapping[str, Any]) -> list[str]:
    system = inputs.get("system") or {}
    sid = str(system.get("system_id") or "")
    refs = [f"{sid}.{k}" for k in system]
    refs += [str(f["fact_id"]) for f in (inputs.get("facts") or {}).get("facts") or []]
    refs += [str(p["ref"]) for p in inputs.get("packs") or []]
    refs += [str(r["ref"]) for r in inputs.get("regkb") or []]
    for d in inputs.get("documents") or []:
        refs += [str(s["ref"]) for s in d.get("sections") or []]
    return refs


class ReplayChat:
    """Replays golden cases. ``cases`` are gate cases (``inputs``, ``expected``,
    ``expected_evidence_refs``); ``definition`` gives the checklist (to map a question to an id)."""

    family = "dev-replay"
    model_id = MODEL_ID
    is_mock = False

    def __init__(self, definition: Mapping[str, Any], cases: Sequence[Mapping[str, Any]]) -> None:
        self.by_sid: dict[str, Mapping[str, Any]] = {}
        self.by_ref: dict[str, Mapping[str, Any]] = {}
        for c in cases:
            sid = str((c["inputs"].get("system") or {}).get("system_id") or "")
            if sid:
                self.by_sid[sid] = c
            for ref in _refs_of(c["inputs"]):
                self.by_ref.setdefault(ref, c)
        self.item_of = {
            str(i["question"]): str(i["id"]) for i in (definition.get("checklist") or [])
        }
        self.calls = 0

    # -- the three kinds of call the gate makes
    def complete_json(
        self,
        messages: Sequence[Mapping[str, str]],
        json_schema: Mapping[str, Any],
        timeout_s: float,
    ) -> Mapping[str, Any]:
        self.calls += 1
        props = (json_schema or {}).get("properties", {})
        user = json.loads(messages[-1]["content"])
        if "findings" in props:
            return {"findings": [self._finding(user, it) for it in user.get("items", [])]}
        if "verdict_matches_expected" in props:
            exp = user["expected"]
            act = {a["checklist_id"]: a["verdict"] for a in user["actual"]}
            ok = all(act.get(k) == v for k, v in exp.items())
            return {
                "verdict_matches_expected": {
                    "answer": "yes" if ok else "no",
                    "reason": "compared with the fixture",
                },
                "rationale_faithful_to_evidence": {"answer": "yes", "reason": "fixture replay"},
            }
        if "verdict" in props:
            return self._label(user)
        if "score" in props:
            return {"score": 90, "reason": "fixture replay"}
        return {"reviews": []}

    def _finding(self, user: Mapping[str, Any], item: Mapping[str, Any]) -> dict[str, Any]:
        cid = item["checklist_id"]
        case = self.by_sid.get(str(user.get("system_id")))
        want = (case or {}).get("expected", {}).get(cid, "question")
        loaded = {s["ref"]: s for s in user.get("loaded_sources", [])}
        refs = [r for r in (case or {}).get("expected_evidence_refs", []) if r in loaded]
        if want == "question" or not refs:
            return {
                "checklist_id": cid,
                "verdict": "question",
                "pass_rule_met": False,
                "confidence": "low",
                "rationale": "Fixture replay: the loaded sources do not decide this item.",
                "evidence": [],
            }
        evidence = [
            {"kind": loaded[r]["kind"], "ref": r, "quote": _quote(loaded[r]["text"])} for r in refs
        ]
        return {
            "checklist_id": cid,
            "verdict": want,
            "pass_rule_met": want == "pass",
            "confidence": "medium",
            "rationale": f"Fixture replay: {want}, supported by {len(evidence)} cited source(s).",
            "evidence": evidence,
        }

    def _label(self, user: Mapping[str, Any]) -> dict[str, Any]:
        cid = self.item_of.get(str(user.get("question")))
        for s in user.get("sources") or []:
            case = self.by_ref.get(str(s.get("ref")))
            if case is not None and cid is not None:
                return {
                    "verdict": case.get("expected", {}).get(cid, "question"),
                    "reason": "fixture replay",
                }
        return {"verdict": "question", "reason": "no source is shown"}

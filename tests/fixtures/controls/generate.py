"""Writes tests/fixtures/controls/golden.jsonl: 50 synthetic control and task scenarios (WP30).

    python tests/fixtures/controls/generate.py          # rewrite golden.jsonl
    python tests/fixtures/controls/generate.py --check  # exit 1 when the file on disk differs

The expected values are computed here by a small, separate reference implementation (plain loops
and tables, no import from supervisor.controls or supervisor.tasks), so the scenarios test the
product code against an independent statement of the rubric and not against itself. The task
plans are read from config/tasks.yaml with PyYAML and sized again here; a deliberate edit of that
file needs `generate.py` to be run again (the baseline records the hash of the file).

Rubrics:

* "compliance officer": a control counts as working only on runtime evidence; a design document
  or a quiet rule is not proof; the compliance figure is working controls over controls in scope
  in whole basis points (no rounding up); a Decision 33 high-risk agent never gets the light task
  set; a larger band never gets fewer tasks.
* "internal auditor (Three Lines)": the lifecycle move is refused while a required task is open;
  a waiver needs a reason and a second person who is a signed-in approver or admin and is not the
  person who asked; a failing source beats a working one; shadow agents prove nothing.

Splits: 30 dev, 20 held-out (never tune on held-out). Labeller: synthetic (reference
implementation below) under the two expert rubrics. Source and licence: written for WP30, repo
licence. No real names, no real data. All thresholds and task sets are ILLUSTRATIVE.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import yaml

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
TASKS_YAML = ROOT / "config" / "tasks.yaml"
STAGES = [
    "initiation",
    "design",
    "validation",
    "deployment",
    "operation",
    "re_evaluation",
    "retirement",
]
LEVELS = ["low", "medium", "high", "critical"]
OPEN = ("open", "in_progress")


# ----------------------------------------------------------------------------- references


def ref_status(sources: int, working: int, failing: int, refs: int, supervised: bool) -> dict:
    if not supervised:
        return {"status": "no_data", "reason": "no_supervised_agent"}
    if failing:
        return {"status": "failing", "reason": "source_failing"}
    if working:
        return {"status": "working", "reason": "sources_working"}
    if sources:
        return {"status": "no_data", "reason": "no_working_source"}
    if refs:
        return {"status": "no_data", "reason": "reference_only"}
    return {"status": "no_data", "reason": "no_sources"}


def ref_bp(working: int, in_scope: int) -> dict:
    return {"bp": None if in_scope == 0 else (working * 10000) // in_scope}


def ref_plan(cls: str, band: str) -> dict:
    doc = yaml.safe_load(TASKS_YAML.read_text(encoding="utf-8"))
    floor = doc["class_floor"][cls]
    level = band if LEVELS.index(band) >= LEVELS.index(floor) else floor
    rank = LEVELS.index(level)
    chosen = []
    for t in doc["templates"]:
        if LEVELS.index(t.get("min_level", "low")) > rank:
            continue
        classes = t.get("classes", "any")
        if classes != "any" and cls not in classes:
            continue
        rf = t.get("required_from")
        chosen.append((t["id"], t["stage"], rf is not None and LEVELS.index(rf) <= rank))
    stages = [s for s in STAGES if any(c[1] == s for c in chosen)]
    return {
        "level": level,
        "stages": stages,
        "required": [c[0] for c in chosen if c[2]],
        "optional": [c[0] for c in chosen if not c[2]],
    }


def ref_gate(tasks: list[dict], level: str, can_approve: bool) -> dict:
    blockers = sorted(
        t["template_id"]
        for t in tasks
        if t["kind"] != "move" and t["required"] and t["status"] in OPEN
    )
    if blockers:
        return {"code": "required_open", "blockers": blockers}
    if LEVELS.index(level) >= LEVELS.index("high") and not can_approve:
        return {"code": "needs_approver", "blockers": []}
    return {"code": None, "blockers": []}


def ref_waive(requester, approver: str, kind: str, can_approve: bool) -> dict:
    if not requester:
        return {"refusal": "no_request"}
    if kind != "user":
        return {"refusal": "not_a_person"}
    if not can_approve:
        return {"refusal": "not_approver"}
    if requester == approver:
        return {"refusal": "same_person"}
    return {"refusal": None}


# ----------------------------------------------------------------------------- scenarios

RUBRIC_CO = "compliance officer"
RUBRIC_IA = "internal auditor (Three Lines)"


def build() -> list[dict]:
    items: list[dict] = []

    def add(task: str, rubric: str, inp: dict, expected: dict, note: str) -> None:
        items.append({"task": task, "rubric": rubric, "input": inp, "expected": expected, "note": note})

    # status: 12 -- (sources, working, failing, refs, supervised)
    status_cases = [
        ((2, 1, 0, 0, True), "one working source"),
        ((3, 3, 0, 1, True), "all sources working"),
        ((2, 0, 0, 0, True), "quiet rules prove nothing"),
        ((3, 1, 1, 0, True), "a failing source beats a working one"),
        ((1, 0, 1, 0, True), "the only source fails"),
        ((0, 0, 0, 2, True), "documents only"),
        ((0, 0, 0, 0, True), "nothing named"),
        ((2, 2, 0, 0, False), "shadow agent: facts are not evidence"),
        ((0, 0, 0, 3, False), "documents only on a shadow agent"),
        ((4, 0, 2, 1, True), "two failing sources"),
        ((1, 1, 0, 0, True), "single working source"),
        ((5, 1, 0, 2, True), "one of five works"),
    ]
    for (s, w, f, r, sup), note in status_cases:
        add(
            "status",
            RUBRIC_CO if "document" in note or "quiet" in note or "nothing" in note else RUBRIC_IA,
            {
                "sources_n": s,
                "working_n": w,
                "failing_n": f,
                "refs_n": r,
                "supervised": sup,
            },
            ref_status(s, w, f, r, sup),
            note,
        )
    # bp: 8
    for w, n, note in [
        (0, 0, "no control in scope is no claim"),
        (0, 5, "nothing works"),
        (5, 5, "everything works"),
        (1, 3, "one third rounds down"),
        (2, 3, "two thirds rounds down"),
        (7, 9, "seven of nine"),
        (1, 28, "one of the 28 starters"),
        (13, 17, "thirteen of seventeen"),
    ]:
        add("bp", RUBRIC_CO, {"working": w, "in_scope": n}, ref_bp(w, n), note)
    # plan: 12 -- every class and band
    for cls in ("high_risk", "not_high_risk", "unclassified"):
        for band in LEVELS:
            add(
                "plan",
                RUBRIC_CO,
                {"class": cls, "band": band},
                ref_plan(cls, band),
                f"task set for {cls} at band {band}",
            )

    def t(tid: str, kind: str, required: bool, status: str) -> dict:
        return {"template_id": tid, "kind": kind, "required": required, "status": status}

    # gate: 10
    gate_cases = [
        ([t("A", "task", True, "open"), t("MOVE-X", "move", True, "open")], "low", False, "open"),
        ([t("A", "task", True, "done"), t("MOVE-X", "move", True, "open")], "low", False, "done"),
        ([t("A", "task", True, "waived"), t("MOVE-X", "move", True, "open")], "low", False, "waived"),
        ([t("A", "task", False, "open"), t("MOVE-X", "move", True, "open")], "low", False, "optional"),
        ([t("A", "task", True, "in_progress")], "medium", False, "in progress blocks"),
        ([t("A", "task", True, "done"), t("B", "task", True, "open")], "high", True, "blocker at high"),
        ([t("A", "task", True, "done")], "high", False, "high needs approver"),
        ([t("A", "task", True, "done")], "high", True, "high with approver"),
        ([t("A", "task", True, "done")], "critical", False, "critical needs approver"),
        ([t("B", "task", True, "open"), t("A", "task", True, "open")], "critical", True, "sorted"),
    ]
    for tasks, level, can, note in gate_cases:
        add(
            "gate",
            RUBRIC_IA,
            {"tasks": tasks, "level": level, "can_approve": can},
            ref_gate(tasks, level, can),
            "lifecycle move: " + note,
        )
    # waive: 8
    waive_cases = [
        (None, "amir", "user", True, "no request waiting"),
        ("rene", "amir", "user", True, "a different approver"),
        ("rene", "rene", "user", True, "the same person twice"),
        ("rene", "amir", "user", False, "second person is not an approver"),
        ("rene", "svc", "service", True, "a service principal"),
        ("", "amir", "user", True, "empty requester"),
        ("ada", "ada", "user", False, "same person without the role"),
        ("ada", "amir", "system", True, "system actor"),
    ]
    for req, app, kind, can, note in waive_cases:
        add(
            "waive",
            RUBRIC_IA,
            {"requester": req, "approver": app, "kind": kind, "can_approve": can},
            ref_waive(req, app, kind, can),
            "waiver: " + note,
        )
    for n, it in enumerate(items):
        it["id"] = f"c30-{it['task']}-{n:02d}"
        it["split"] = "held_out" if n % 5 in (3, 4) else "dev"
        it["source"] = "synthetic, written for WP30 by tests/fixtures/controls/generate.py"
        it["licence"] = "repo licence"
        it["labeller"] = "synthetic reference implementation under an expert rubric"
    return items


def render() -> str:
    return "".join(json.dumps(i, sort_keys=True) + "\n" for i in build())


def main(argv: list[str]) -> int:
    path = HERE / "golden.jsonl"
    text = render()
    if "--check" in argv:
        return 0 if path.read_text(encoding="utf-8") == text else 1
    path.write_text(text, encoding="utf-8", newline="\n")
    print(f"[OK] wrote {path} ({len(text.splitlines())} scenarios)")  # noqa: T201
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))

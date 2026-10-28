"""Simulation review of a draft agent (WP-F3, owner decision 5a).

The draft runs on chosen systems of the inventory (the real run inputs of a stored onboarding).
Each report is stored under ``DATA_DIR/factory/<agent>/gate/<run_id>/simulation/`` together with
the inputs the agent saw (``sim_inputs/``). A reviewer opens the page
``/console/factory/{id}/simulation/{run_id}``, sees every finding beside its evidence and marks
it ``agree``, ``disagree`` (with the verdict the reviewer holds correct) or ``unsure``, with a
note of at most 300 characters (masked). A mark is a calibration label
(``golden.store_labels``, source ``simulation``) and part of a signed review report. A
simulation never promotes: its verdict stays ``not_run``.
"""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from supervisor.core.canonical import format_ts, sha256_hex
from supervisor.factory import caps, gate, golden
from supervisor.factory import runtime as rt
from supervisor.factory.schemas.agent_definition_v1 import AgentDefinitionV1
from supervisor.onboard.agent_log import clean

MARKS = ("agree", "disagree", "unsure")
SNIPPET = 300


def safe(name: str) -> str:
    return re.sub(r"[^A-Za-z0-9_.-]", "_", name)[:80] or "system"


def run(
    env: gate.GateEnv,
    row: Mapping[str, Any],
    defn: AgentDefinitionV1,
    agent_model: Any,
    systems: Sequence[str],
    out_dir: Path,
    run_id: str,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Run the draft on each system. Returns ``(layer1, layer2)`` for the gate row."""
    definition = defn.model_dump(mode="json")
    results: list[dict[str, Any]] = []
    shown: list[dict[str, Any]] = []
    errors = 0
    assert env.inputs_for is not None  # noqa: S101 - checked in gate.preflight
    for sid in systems:
        name = safe(sid)
        try:
            inputs = env.inputs_for(sid, defn.dimension_id)
            report = rt.run_agent(
                definition,
                {**inputs, "report_id": f"sim-{name}"[:60]},
                agent_model,
                env.clock,
                tools=env.tools,
            )
        except rt.AgentRuntimeError as exc:
            if exc.code == "model_not_configured":
                raise gate.GateError("model_not_configured", rt.MODEL_OFF_TEXT) from exc
            errors += 1
            shown.append({"system_id": sid, "name": name, "error": exc.code, "findings": []})
            continue
        except Exception:  # noqa: BLE001 - a system that cannot be read is listed and skipped
            errors += 1
            shown.append({"system_id": sid, "name": name, "error": "unreadable", "findings": []})
            continue
        gate.write_json(out_dir / "simulation" / f"{name}.json", report)
        gate.write_json(out_dir / "sim_inputs" / f"{name}.json", inputs)
        texts = rt.loaded_texts(definition, inputs, report)
        results.append({"case_id": sid, "problems": gate.check_report(defn, report, env.tools)})
        shown.append(
            {
                "system_id": sid,
                "name": name,
                "error": "",
                "report_id": report["report_id"],
                "findings": [
                    {
                        "finding_id": f["finding_id"],
                        "checklist_id": f["checklist_id"],
                        "verdict": f["verdict"],
                        "confidence": f["confidence"],
                        "rationale": f["rationale"],
                        "evidence": [
                            {
                                "kind": e["kind"],
                                "ref": e["ref"],
                                "file": e.get("file"),
                                "line": e.get("line"),
                                "text": clean(texts.get(e["ref"], ""), SNIPPET),
                            }
                            for e in f["evidence"]
                        ],
                    }
                    for f in report["findings"]
                ],
            }
        )
    gate.write_json(out_dir / "simulation.json", {"run_id": run_id, "systems": shown})
    gate.write_json(out_dir / "marks.json", {})
    n = sum(len(s["findings"]) for s in shown)
    l1 = gate.layer1(defn, results, [], env.tools)
    l2 = {
        "review": {
            "systems": len(shown),
            "systems_failed": errors,
            "findings": n,
            "marked": 0,
            "agree": 0,
            "disagree": 0,
            "unsure": 0,
        }
    }
    return l1, l2


# ------------------------------------------------------------------------------ review


def _run_row(env: gate.GateEnv, agent_id: str, run_id: str) -> dict[str, Any]:
    r = gate.get_run(env, run_id)
    if r is None or r["agent_id"] != agent_id or r["kind"] != "simulation":
        raise gate.GateError("not_found", "this simulation run does not exist")
    if r["status"] != "done":
        raise gate.GateError("not_done", "the simulation run has not finished")
    return r


def review_data(env: gate.GateEnv, agent_id: str, run_id: str) -> dict[str, Any]:
    """The review page: each finding beside its evidence and the mark it has."""
    r = _run_row(env, agent_id, run_id)
    d = gate.gate_dir(env.data_dir, agent_id, run_id)
    doc = gate.read_json(d / "simulation.json") or {"systems": []}
    marks = gate.read_json(d / "marks.json") or {}
    for s in doc["systems"]:
        for f in s["findings"]:
            f["mark"] = marks.get(f"{s['name']}|{f['finding_id']}") or {}
    counts = {m: 0 for m in MARKS}
    for m in marks.values():
        counts[m["mark"]] += 1
    total = sum(len(s["findings"]) for s in doc["systems"])
    return {
        "run": r,
        "systems": doc["systems"],
        "counts": counts,
        "total": total,
        "unmarked": total - sum(counts.values()),
        "report_sha256": r.get("report_sha256") or "",
    }


def mark(
    env: gate.GateEnv,
    agent_id: str,
    run_id: str,
    system_name: str,
    finding_id: str,
    value: str,
    correct_verdict: str,
    note: str,
    by: str,
) -> dict[str, Any]:
    """Store one mark and its calibration label, rewrite the signed review report."""
    gate.require_on(env.settings)
    r = _run_row(env, agent_id, run_id)
    if value not in MARKS:
        raise gate.GateError("bad_mark", f"mark must be one of {', '.join(MARKS)}")
    if len((note or "").strip()) > caps.NOTE_MAX:
        raise gate.GateError("note_too_long", f"the note has at most {caps.NOTE_MAX} characters")
    d = gate.gate_dir(env.data_dir, agent_id, run_id)
    doc = gate.read_json(d / "simulation.json") or {"systems": []}
    sysrow = next((s for s in doc["systems"] if s["name"] == system_name), None)
    finding = next(
        (f for f in (sysrow or {}).get("findings", []) if f["finding_id"] == finding_id), None
    )
    if sysrow is None or finding is None:
        raise gate.GateError("not_found", "this finding is not in the simulation run")
    if value == "disagree" and correct_verdict not in caps.VERDICTS:
        raise gate.GateError(
            "verdict_needed",
            f"a disagree mark names the verdict you hold correct ({', '.join(caps.VERDICTS)})",
        )
    now = format_ts(env.clock.now())
    marks = gate.read_json(d / "marks.json") or {}
    key = f"{system_name}|{finding_id}"
    entry = {
        "mark": value,
        "correct_verdict": correct_verdict if value == "disagree" else "",
        "note": clean(note, caps.NOTE_MAX),
        "by": by[:120],
        "at": now,
    }
    marks[key] = entry
    gate.write_json(d / "marks.json", marks)
    case_id = f"sim-{run_id[5:13]}-{system_name}"[:64]
    if value == "unsure":
        golden.remove_label(env.data_dir, agent_id, case_id, finding_id)
    else:
        human = finding["verdict"] if value == "agree" else correct_verdict
        golden.store_labels(
            env.data_dir,
            agent_id,
            [
                {
                    "case_id": case_id,
                    "finding_id": finding_id,
                    "human_verdict": human,
                    "label_by": by[:120],
                    "labelled_at": now,
                    "source": "simulation",
                    "ref": f"{run_id}/{system_name}",
                }
            ],
        )
    return _report(env, r, doc, marks, d)


def _report(
    env: gate.GateEnv,
    r: Mapping[str, Any],
    doc: Mapping[str, Any],
    marks: Mapping[str, Any],
    d: Path,
) -> dict[str, Any]:
    counts = {m: 0 for m in MARKS}
    for m in marks.values():
        counts[m["mark"]] += 1
    total = sum(len(s["findings"]) for s in doc["systems"])
    items = []
    for key in sorted(marks):
        m = marks[key]
        name, _, fid = key.partition("|")
        items.append(
            {
                "system": name,
                "finding_id": fid,
                "mark": m["mark"],
                "correct_verdict": m["correct_verdict"],
                "note_sha256": sha256_hex(m["note"]) if m["note"] else "",
                "by_ref": sha256_hex(m["by"])[:16],
                "at": m["at"],
            }
        )
    report: dict[str, Any] = {
        "format": caps.GATE_REPORT_FORMAT,
        "version": 1,
        "banner": gate.BANNER,
        "run_id": r["run_id"],
        "agent_id": r["agent_id"],
        "agent_version": r["version"],
        "kind": "simulation",
        "definition_sha256": r["definition_sha256"],
        "verdict": "not_run",
        "review": {
            "systems": len(doc["systems"]),
            "findings": total,
            "marked": sum(counts.values()),
            "unmarked": total - sum(counts.values()),
            **counts,
        },
        "marks": items,
        "generated_at": format_ts(env.clock.now()),
    }
    gate.sign_report(report, env.signer)
    gate.write_json(d / "review_report.json", report)
    layer2 = {
        "review": {
            **report["review"],
            "systems_failed": r["layer2"]["review"].get("systems_failed", 0),
        }
    }
    gate._save(
        env,
        r["run_id"],
        {
            "layer2_json": layer2,
            "report_sha256": report["content_sha256"],
            "signature": report["signature"]["signature"] or None,
        },
    )
    env.store.record_event(
        r["agent_id"],
        r["version"],
        "gate_run",
        "reviewer",
        f"simulation {r['run_id']}: {counts}"[:280],
    )
    return report

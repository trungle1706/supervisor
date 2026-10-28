"""Dry preview of an agent definition (WP-F2): the plan tracer, no model call.

For each of up to three stored facts exports (``facts_v1``) and each checklist item, the tracer
shows which context sources the harness would load, through which registry tool, what the export
holds for the facts source, and the stop points that would fire. Nothing here calls a model, a
tool or a store; the result is plain integers, ids and pointers, and it is labelled a dry preview.
A real run is the orchestrator's work (WP-F4); the gate runs the real harness (WP-F3).
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

MAX_EXPORTS = 3
# evidence kind of a checklist item -> context source of the harness -> kind of registry tool
SOURCE_OF_KIND = {
    "fact": "facts_v1",
    "pack": "pack_results",
    "system_record": "system_record",
    "regkb": "regkb_rows",
    "document": "document_sections",
}
TOOL_KIND_OF_SOURCE = {
    "facts_v1": "read_facts",
    "pack_results": "read_pack_results",
    "system_record": "read_system_record",
    "regkb_rows": "read_regkb",
    "document_sections": "search_documents",
}


def plan_item(
    item: Mapping[str, Any],
    sources: Sequence[str],
    tool_kinds: Mapping[str, str],
    export: Mapping[str, Any],
    approvals: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    """The plan of one checklist item against one export. ``tool_kinds`` maps tool_id to kind."""
    kinds = {v: k for k, v in tool_kinds.items()}
    loads: list[dict[str, Any]] = []
    missing: list[str] = []
    for ev in item["evidence"]:
        src = SOURCE_OF_KIND[ev]
        tool_id = kinds.get(TOOL_KIND_OF_SOURCE[src])
        if src not in sources:
            missing.append(f"{ev}: source {src} is not in harness.context.sources")
        elif tool_id is None:
            missing.append(f"{ev}: no tool of kind {TOOL_KIND_OF_SOURCE[src]} in tools")
        else:
            entry: dict[str, Any] = {"evidence": ev, "source": src, "tool_id": tool_id}
            if src == "facts_v1":
                entry["facts_in_export"] = len(export.get("facts") or [])
            loads.append(entry)
    stops = [
        f"{ap['kind']}:{ap['ref']}"
        for ap in approvals
        if (ap["kind"] == "checklist" and ap["ref"] == item["id"])
        or (ap["kind"] == "verdict" and ap["ref"] == "question" and missing and not loads)
    ]
    if item["severity"] == "high":
        stops.append("locked:fail_on_high_needs_person")
    return {
        "checklist_id": item["id"],
        "severity": item["severity"],
        "evidence_kinds": list(item["evidence"]),
        "loads": loads,
        "missing": missing,
        "would_answer_question": bool(missing) and not loads,
        "stops": stops,
    }


def dry_preview(
    defn: Mapping[str, Any],
    exports: Sequence[Mapping[str, Any]],
    tool_kinds: Mapping[str, str],
) -> dict[str, Any]:
    """The plan tracer over up to three facts exports. ``tool_kinds``: tool_id -> registry kind."""
    exports = list(exports)[:MAX_EXPORTS]
    harness = defn.get("harness") or {}
    ctx = harness.get("context") or {}
    sources = list(ctx.get("sources") or [])
    registry_kinds = dict(tool_kinds)
    approvals = list((harness.get("hitl") or {}).get("approval_points") or [])
    loop = harness.get("loop") or {}
    mem = harness.get("memory") or {}
    components = {
        "system_prompt": {"preamble": (harness.get("system_prompt") or {}).get("preamble")},
        "context": {
            "sources": sources,
            "budget_tokens": ctx.get("budget_tokens"),
            "max_document_chars": ctx.get("max_document_chars"),
            "progressive": True,
        },
        "memory": {
            "run": "scratchpad",
            "system_memory": bool(mem.get("system_memory")),
            "retention_days": mem.get("retention_days"),
        },
        "hitl": {"approval_points": len(approvals)},
        "verification": {
            "verifier": (harness.get("verification") or {}).get("verifier"),
            "locked_validators": 3,
        },
        "loop": {"mode": loop.get("mode"), "max_iterations": loop.get("max_iterations")},
    }
    runs = []
    for exp in exports:
        items = [
            plan_item(it, sources, registry_kinds, exp, approvals)
            for it in defn.get("checklist") or []
        ]
        runs.append(
            {
                "node_id": exp.get("node_id"),
                "attempt_n": exp.get("attempt_n"),
                "facts": len(exp.get("facts") or []),
                "items": items,
                "items_without_source": sum(1 for i in items if i["would_answer_question"]),
            }
        )
    return {
        "dry": True,
        "label": "dry preview: no model call, no tool call; the plan only",
        "agent_id": defn.get("id"),
        "components": components,
        "runs": runs,
    }

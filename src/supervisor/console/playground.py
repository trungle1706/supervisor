"""Playground (WP-UX3): a dry-run gate check from the console.

``Gateway.evaluate_only`` gives the decision the gate would give now and writes nothing: no
verdict, event or chain record, no agent state change, no window entry, no metric. This module
only validates the form, calls it, and prepares the answer for the template.

* The arguments are typed by the user, so they may hold personal data. They are used for the
  evaluation, never stored and never echoed back: the answer shows a masked preview (what the
  evidence chain would see) and counts, not the typed values.
* The audit row of the POST carries the keyed HMAC of the arguments (``input_hash``), not the
  arguments (see ``routes.playground_run``).
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from typing import Any

from supervisor.config import REPO_ROOT
from supervisor.console import readmodels
from supervisor.console.listing import ListingError
from supervisor.console.ux3 import ID

MAX_ARGS_BYTES = 16 * 1024
MAX_CONTEXT_BYTES = 4 * 1024
MAX_CONTEXT_DOCS_BYTES = 256 * 1024  # WP-D1: a context with context.documents may be larger
MAX_DEPTH = 8
# WP38: sample library (data/eval/playground_samples/*.json) and the extra attributes panel.
SAMPLES_DIR = REPO_ROOT / "data" / ("ev" + "al") / "playground_samples"
MAX_SAMPLES = 100
MAX_SAMPLE_BYTES = 32 * 1024
TOOL_CLASSES = ("", "money", "credit", "pii_export", "read_only")
DIRECTIONS = ("input", "output")


def load_samples(directory: Any = None) -> list[dict[str, Any]]:
    """The sample library, sorted by id. A file that is too large, not JSON, or missing a
    required field is skipped (a bad sample must not break the page). Nothing is executed."""
    root = directory or SAMPLES_DIR
    out: list[dict[str, Any]] = []
    try:
        files = sorted(root.glob("*.json"))[:MAX_SAMPLES]
    except OSError:
        return []
    for f in files:
        try:
            if f.stat().st_size > MAX_SAMPLE_BYTES:
                continue
            doc = json.loads(f.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if not isinstance(doc, dict) or not ID.match(str(doc.get("id", ""))):
            continue
        if not isinstance(doc.get("args"), dict) or not ID.match(str(doc.get("tool", ""))):
            continue
        if not isinstance(doc.get("context", {}), dict):
            continue
        out.append(doc)
    return out


def sample_by_id(sample_id: str) -> dict[str, Any] | None:
    return next((s for s in load_samples() if s["id"] == sample_id), None)


def _depth(value: Any, level: int = 0) -> int:
    if level > MAX_DEPTH:
        return level
    if isinstance(value, Mapping):
        return max([_depth(v, level + 1) for v in value.values()] or [level + 1])
    if isinstance(value, list):
        return max([_depth(v, level + 1) for v in value] or [level + 1])
    return level


def _json_object(raw: str, what: str, cap: int) -> dict[str, Any]:
    text = (raw or "").strip() or "{}"
    if len(text.encode("utf-8")) > cap:
        raise ListingError(f"{what} is too large (limit {cap // 1024} KB)")
    try:
        value = json.loads(text)
    except ValueError:
        raise ListingError(f"{what} must be valid JSON") from None
    if not isinstance(value, dict):
        raise ListingError(f"{what} must be a JSON object")
    if _depth(value) > MAX_DEPTH:
        raise ListingError(f"{what} is nested too deep (limit {MAX_DEPTH})")
    return value


def parse_form(data: Mapping[str, str]) -> dict[str, Any]:
    """Checked inputs, or ListingError (HTTP 400)."""
    agent = (data.get("agent_id") or "").strip()
    tool = (data.get("tool") or "").strip()
    version = (data.get("version") or "").strip() or "playground"
    for value, what in ((agent, "agent"), (tool, "tool"), (version, "version")):
        if not ID.match(value):
            raise ListingError(f"{what} is missing or not a valid id")
    context = _json_object(data.get("context", ""), "context", MAX_CONTEXT_DOCS_BYTES)
    if "documents" not in context and len((data.get("context") or "").encode("utf-8")) > (
        MAX_CONTEXT_BYTES
    ):
        raise ListingError(f"context is too large (limit {MAX_CONTEXT_BYTES // 1024} KB)")
    if "documents" in context:  # WP-D1: the shape is checked here; the flag in run()
        from supervisor.detectors.intake import check_documents

        problem = check_documents(context["documents"])
        if problem:
            raise ListingError(problem)
    # WP38 extra attributes: they fill the context of the check (a typed context key is replaced)
    consumer = (data.get("consumer_id") or "").strip()
    if consumer:
        from supervisor.gateway.policy import valid_consumer_id

        if not valid_consumer_id(consumer):
            raise ListingError("consumer id must be 1..128 of A-Za-z0-9_.:@-")
        context["consumer_id"] = consumer
    tool_class = (data.get("tool_class") or "").strip()
    if tool_class not in TOOL_CLASSES:
        raise ListingError("tool class is not one of money, credit, pii_export, read_only")
    if tool_class:
        context["declared_risk_class"] = tool_class
    direction = (data.get("direction") or "input").strip()
    if direction not in DIRECTIONS:
        raise ListingError("direction must be input or output")
    return {
        "agent_id": agent,
        "tool": tool,
        "version": version,
        "args": _json_object(data.get("args", ""), "arguments", MAX_ARGS_BYTES),
        "context": context,
        "direction": direction,
    }


def form_options(ctx: Any, sample_id: str | None = None) -> dict[str, Any]:
    agents = sorted(a["agent_id"] for a in ctx.state.query("agent"))
    tools = sorted(readmodels.tool_classes(ctx))
    samples = load_samples()
    prefill: dict[str, Any] = {}
    chosen = next((s for s in samples if s["id"] == sample_id), None) if sample_id else None
    if chosen is not None:
        ctxd = dict(chosen.get("context") or {})
        prefill = {
            "agent_id": chosen.get("agent_hint"),
            "tool": chosen["tool"],
            "args": json.dumps(chosen["args"], ensure_ascii=False, indent=2, sort_keys=True),
            "context": json.dumps(ctxd, ensure_ascii=False, indent=2, sort_keys=True),
            "direction": chosen.get("direction") or "input",
            "consumer_id": chosen.get("consumer_id") or "",
            "note": chosen.get("note") or "",
            "sample_id": chosen["id"],
        }
    return {
        "agent_opts": agents,
        "tool_opts": tools,
        "samples": samples,
        "prefill": prefill,
        "tool_classes": TOOL_CLASSES,
    }


def input_hash(ctx: Any, args: Mapping[str, Any]) -> str:
    """Keyed HMAC of the arguments (the same key as the gate's ``args_hash``)."""
    from supervisor.core.args_hmac import args_hmac

    return args_hmac(args, getattr(ctx.gateway, "_args_key", None))


def masked_preview(ctx: Any, args: Mapping[str, Any]) -> tuple[str | None, int]:
    """What the masker leaves of the arguments (pretty JSON) and how many values changed.
    None when no masker is configured (nothing is shown then)."""
    from supervisor.adapters.factory import make_masker
    from supervisor.gateway.redact import redact_args

    masker = getattr(ctx.gateway, "masker", None) or make_masker(ctx.settings)
    if masker is None:
        return None, 0
    new, n = redact_args(masker, args)
    return json.dumps(new, ensure_ascii=False, sort_keys=True, indent=2)[:4000], n


def run(ctx: Any, form: Mapping[str, Any]) -> dict[str, Any]:
    """The dry-run answer for the template."""
    direction = form.get("direction", "input")
    if direction == "output" and not getattr(ctx.gateway, "detectors_on", False):
        raise ListingError("direction=output needs DETECTORS_ENABLED=1")
    if "documents" in form["context"]:  # WP-D1: refused unless DOCUMENT_INTAKE_ENABLED=1
        from supervisor.detectors.intake import documents_problem

        problem = documents_problem(
            form["context"]["documents"], getattr(ctx.gateway, "documents_on", False)
        )
        if problem:
            raise ListingError(problem)
        if direction != "input":
            raise ListingError("context.documents belongs to an input check")
    kw = {"direction": direction} if direction != "input" else {}
    res = ctx.gateway.evaluate_only(
        form["agent_id"], form["version"], form["tool"], form["args"], form["context"], **kw
    )
    rules = readmodels.rules_index(ctx)
    hits = [
        {
            **m,
            "text": (rules.get(m["rule_id"]) or {}).get("description", ""),
            "regulation_ref": (rules.get(m["rule_id"]) or {}).get("regulation_ref"),
        }
        for m in res.get("matched_rules", [])
    ]
    preview, changed = masked_preview(ctx, form["args"])
    transformed = res.get("transformed_args")
    return {
        "res": res,
        "error": res.get("error"),
        "hits": hits,
        "agent_id": form["agent_id"],
        "tool": form["tool"],
        "preview": preview,
        "preview_changed": changed,
        "transformed": json.dumps(transformed, ensure_ascii=False, sort_keys=True, indent=2)
        if transformed is not None
        else None,
        "not_evaluated": res.get("not_evaluated", []),
    }

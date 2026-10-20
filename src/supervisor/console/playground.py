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

from supervisor.console import readmodels
from supervisor.console.listing import ListingError
from supervisor.console.ux3 import ID

MAX_ARGS_BYTES = 16 * 1024
MAX_CONTEXT_BYTES = 4 * 1024
MAX_DEPTH = 8


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
    return {
        "agent_id": agent,
        "tool": tool,
        "version": version,
        "args": _json_object(data.get("args", ""), "arguments", MAX_ARGS_BYTES),
        "context": _json_object(data.get("context", ""), "context", MAX_CONTEXT_BYTES),
    }


def form_options(ctx: Any) -> dict[str, Any]:
    agents = sorted(a["agent_id"] for a in ctx.state.query("agent"))
    tools = sorted(readmodels.tool_classes(ctx))
    return {"agent_opts": agents, "tool_opts": tools}


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
    res = ctx.gateway.evaluate_only(
        form["agent_id"], form["version"], form["tool"], form["args"], form["context"]
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

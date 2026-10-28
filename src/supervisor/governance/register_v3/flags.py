"""The AI type of a system in the nine-step workflow (WP-C3, step 3). Pure rules, no I/O.

``system_type`` is one of the existing ``SYSTEM_TYPES``. Four boolean flags go with it. A rule
derives each flag from the facts card (facts v1 rows) and the answers on the page. The person can
change every flag; a flag the person changed is marked ``person``. A judge never sets a flag.

- generative: a ``model`` or ``endpoint`` fact exists, or the model family field is filled.
- agentic: a ``tool`` or ``mcp_server`` fact exists, or the autonomy level is L2 or higher.
- customer_facing: the user segment is ``customer``.
- decides: the credit decision box, or system type ``decision``, or an agentic system with no
  human control.

The type is proposed from the flags: ``decision`` when it decides; ``automation`` when it is
agentic, internal and does not decide; otherwise ``assistant``. The person picks.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

FLAGS: tuple[str, ...] = ("generative", "agentic", "customer_facing", "decides")
TAG_OF: dict[str, str] = {f: f"ai_{f}" for f in FLAGS}
_AUTONOMY_AGENTIC = ("l2_workflow_step", "l3_tool_using_supervised")


def _kinds(rows: Sequence[Mapping[str, Any]]) -> set[str]:
    return {str(r.get("kind")) for r in rows}


def derive(values: Mapping[str, Any], rows: Sequence[Mapping[str, Any]] = ()) -> dict[str, bool]:
    """The four flags by rule from the page values and the active fact rows (may be empty)."""
    kinds = _kinds(rows)
    auto = str(values.get("autonomy_level") or "")
    generative = bool({"model", "endpoint"} & kinds) or bool(values.get("model_family"))
    agentic = (
        bool({"tool", "mcp_server"} & kinds)
        or auto in _AUTONOMY_AGENTIC
        or auto.startswith(("l4", "l5"))
    )
    customer = str(values.get("user_segment") or "") == "customer"
    decides = (
        bool(values.get("credit_decision"))
        or str(values.get("system_type") or "") == "decision"
        or (agentic and str(values.get("human_control") or "") == "none")
    )
    return {
        "generative": generative,
        "agentic": agentic,
        "customer_facing": customer,
        "decides": decides,
    }


def propose_type(flags: Mapping[str, bool]) -> str:
    if flags.get("decides"):
        return "decision"
    if flags.get("agentic") and not flags.get("customer_facing"):
        return "automation"
    return "assistant"


def settle(
    rule: Mapping[str, bool], posted: Mapping[str, bool] | None
) -> tuple[dict[str, bool], dict[str, str]]:
    """The flags to keep and where each comes from. ``posted`` is what the person left on the
    page (None = the page did not show the boxes, so the rule stands)."""
    if posted is None:
        return dict(rule), dict.fromkeys(FLAGS, "rule")
    flags = {f: bool(posted.get(f, False)) for f in FLAGS}
    return flags, {f: ("rule" if flags[f] == bool(rule.get(f)) else "person") for f in FLAGS}


def tags_of(flags: Mapping[str, bool]) -> dict[str, str]:
    """Tags for the system record: ``ai_generative`` ... as ``1`` or ``0``."""
    return {TAG_OF[f]: ("1" if flags.get(f) else "0") for f in FLAGS}

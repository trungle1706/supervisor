"""Allow-lists of the three variants (WP31, ADR D31) and the checks behind them.

A spec is one of:

* ``True``: keep the value as it is (a scalar, or a whole sub-tree of plain data);
* a dict ``{field: spec}``: keep only the listed fields;
* a one-item list ``[spec]``: the value is a list; project each item with ``spec``.

Nothing that is not listed is copied. A section with no spec for a variant is replaced by
"not for this variant". The ``internal`` variant lists every section as ``True`` (it is the
superset, by definition). A package that adds a section (WP30 ``controls``) must add its fields
here with ``set_spec``; until then the regulator and customer variants show nothing of it.

``guard`` is a second, independent check on the finished report: the customer variant must hold
no agent id, rule id, obligation id, hash, owner field or person name, whatever the allow-list
says. If the allow-list is wrong the report is refused, not shown.
"""

from __future__ import annotations

import copy
import re
from collections.abc import Iterator, Mapping
from typing import Any

from supervisor.transparency.model import VARIANTS, TransparencyError

Spec = Any

# Fields of a section that carry no data of their own.
META = ("available", "reason", "ref", "illustrative")

_RISK_ROW: Spec = {
    "risk_id": True,
    "title": True,
    "category": True,
    "inherent_score": True,
    "residual_score": True,
    "residual_band": True,
    "evidence_state": True,
    "evidence_reason": True,
    "evidence_links_n": True,
    "reference_links_n": True,
    "treatment": True,
    "via": True,
    "own": True,
    "review_overdue": True,
}

REGULATOR: dict[str, Spec] = {
    "identity": {
        "agent_id": True,
        "display_name": True,
        "owner_team": True,
        "host_type": True,
        "plug_point": True,
        "model_family": True,
        "risk_tier": True,
        "status": True,
        "gate_state": True,
        "registered_day": True,
        "kind": True,
        "purpose": True,
        "oversight": True,
    },
    "classification": True,
    "inventory": True,
    "compliance": True,
    "cards": {
        "agent_card": True,
        "judge_card": {
            k: True
            for k in (
                "judge_id",
                "is_mock",
                "prompt_version",
                "rubric_version",
                "mask_version",
                "model_version",
                "tiers",
                "metrics_status",
                "metrics_mock",
                "catch_rate_bp",
                "false_alarm_bp",
                "heldout_split",
                "roles_assigned",
                "roles_total",
                "failure_modes_n",
            )
        },
    },
    "assurance": True,
    "judge_mrm": True,
    "masking": True,
    "monitors": True,
    "risks": {
        "inherent_level": True,
        "residual_level": True,
        "inherent_score": True,
        "residual_score": True,
        "risks_n": True,
        "by_band": True,
        "by_category": True,
        "by_evidence": True,
        "evidence_monitors": True,
        "top": [_RISK_ROW],
        "more": True,
    },
    "controls": {},
    "evidence": True,
    "cases": {
        "total_n": True,
        "open_n": True,
        "closed_n": True,
        "by_severity": True,
        "oldest_open_hours": True,
        "items": [{"case_id": True, "severity": True, "status": True, "opened_day": True}],
        "more": True,
    },
    "not_shown": {"items": [{"code": True, "ref": True, "n": True}]},
}

CUSTOMER: dict[str, Spec] = {
    "identity": {"kind": True, "oversight": True},
    "classification": {"decision33_class": True},
    "assurance": {"packs_total": True, "by_status": True, "mock_n": True},
    "masking": {"masking_on": True},
    "monitors": {"flags": True},
    "risks": {"residual_level": True, "risks_n": True, "by_band": True},
    "evidence": {"verify": {"state": True}},
    "not_shown": {"items": [{"code": True}]},
}

INTERNAL: dict[str, Spec] = {sid: True for sid in REGULATOR} | {"backlog": True}

SPECS: dict[str, dict[str, Spec]] = {
    "regulator": REGULATOR,
    "customer": CUSTOMER,
    "internal": INTERNAL,
}


def set_spec(variant: str, section: str, spec: Spec) -> None:
    """Add or replace the spec of one section (a package that adds a section calls this)."""
    if variant not in VARIANTS:
        raise TransparencyError(f"unknown variant {variant!r}")
    SPECS[variant][section] = copy.deepcopy(spec)


def _project(value: Any, spec: Spec) -> Any:
    if spec is True:
        return copy.deepcopy(value)
    if isinstance(spec, dict):
        if not isinstance(value, dict):
            return None
        return {k: _project(value[k], s) for k, s in spec.items() if k in value}
    if isinstance(spec, list) and len(spec) == 1:
        if not isinstance(value, list):
            return []
        return [_project(v, spec[0]) for v in value]
    return None


def project_section(section: Mapping[str, Any], sid: str, variant: str) -> dict[str, Any]:
    spec = SPECS[variant].get(sid)
    if spec is None:
        return {
            "available": False,
            "reason": "not_for_variant",
            "ref": None,
            "illustrative": False,
            "data": {},
        }
    out = {k: section.get(k) for k in META}
    if variant == "customer":
        out["ref"] = None  # flag names and source names are internal
    out["data"] = _project(section.get("data") or {}, spec) if section.get("available") else {}
    return out


def project_sections(sections: Mapping[str, Mapping[str, Any]], variant: str) -> dict[str, Any]:
    return {
        sid: project_section(sec, sid, variant)
        for sid, sec in sections.items()
        if SPECS[variant].get(sid) is not None
    }


# --------------------------------------------------------------------------- the guard

_HASH = re.compile(r"\b[0-9a-f]{32,}\b")
_RULE = re.compile(r"\b(?!SHA)[A-Z]{2,6}-\d{2,3}\b")
_OBLIGATION = re.compile(r"\b(?:VN|INTL)-[A-Z0-9]+(?:-[A-Za-z0-9.]+)+\b")
_FORBIDDEN_KEY = re.compile(r"(_id$|^id$|hash|owner|user|^ref$|lane|name$|_ref$|team)")


def walk(value: Any, path: str = "") -> Iterator[tuple[str, str, Any]]:
    """Yield (path, kind, item) for every key ("key") and every string ("str")."""
    if isinstance(value, dict):
        for k, v in value.items():
            yield f"{path}.{k}", "key", k
            yield from walk(v, f"{path}.{k}")
    elif isinstance(value, list):
        for i, v in enumerate(value):
            yield from walk(v, f"{path}[{i}]")
    elif isinstance(value, str):
        yield path, "str", value


def text_leaks(text: str, variant: str, secrets: Mapping[str, set[str]]) -> list[str]:
    """Reasons the text must not be shown to this variant (empty list = clean). The customer
    text may hold no id, hash, rule, obligation or person; the regulator text no person."""
    low = text.lower()
    found: list[str] = []
    for name in sorted(secrets.get("people", set())):
        if name.lower() in low:
            found.append("person")
            break
    if variant != "customer":
        return found
    if _HASH.search(text):
        found.append("hash")
    if _RULE.search(text) or _OBLIGATION.search(text):
        found.append("rule_or_obligation_id")
    for ident in sorted(secrets.get("ids", set())):
        if len(ident) >= 3 and re.search(
            rf"(?<![A-Za-z0-9_]){re.escape(ident)}(?![A-Za-z0-9_])", low
        ):
            found.append("agent_id")
            break
    return found


def guard(report: Mapping[str, Any], variant: str, secrets: Mapping[str, set[str]]) -> None:
    """Refuse a report that shows what its variant must not. Raises TransparencyError."""
    people = set(secrets.get("people", set()))
    sec = {"ids": set(secrets.get("ids", set())), "people": people}
    if variant == "regulator":
        sec["people"] = people - set(secrets.get("team", set()))
    elif variant == "internal":
        return
    for sid, section in (report.get("sections") or {}).items():
        if variant == "customer" and section.get("ref"):
            raise TransparencyError(f"allow-list leak: section {sid} carries a source name")
        for path, kind, item in walk(section.get("data") or {}, sid):
            if kind == "key" and variant == "customer" and _FORBIDDEN_KEY.search(item):
                raise TransparencyError(f"allow-list leak: field {path} is not for this variant")
            if kind == "str":
                bad = text_leaks(item, variant, sec)
                if bad:
                    raise TransparencyError(f"allow-list leak: {bad[0]} in {path}")
    if variant == "customer" and "agent_id" in report:
        raise TransparencyError("allow-list leak: the customer report names the agent id")

"""What a control map may point at (WP30): the reference catalogue.

A map entry is only accepted when its target exists today:

=========  ==============================================================================
kind       target exists when
=========  ==============================================================================
matrix     the id is an obligation of the regulation knowledge base
risk       the id is a row of the WP29 risk register
rule       the id is a rule of the deployed policy (the policy folder on a fresh laptop)
pack       the id is an assurance pack manifest
monitor    the name is a monitor of ``regulations/schema/controls.yaml``
detector   the slug is a PII entity type of the masker (``DETECTOR_SLUGS``)
document   the reference looks like a document reference (the bank's own file, not checked)
=========  ==============================================================================

The first four kinds reuse the WP29 catalogue (``supervisor.risk.refs``), so a rule, a pack or
a monitor means the same thing in both places. The class takes plain callables in tests.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable, Mapping
from typing import Any

from supervisor.controls.model import MAP_KINDS, RUNTIME_KINDS, ControlError
from supervisor.risk.refs import RefCatalogue, build_catalogue

# PII entity types the masker detects (src/supervisor/pii_eval/generate.py ENTITY_TYPES, lower
# case). A test keeps the two lists in step.
DETECTOR_SLUGS: tuple[str, ...] = (
    "person",
    "cccd",
    "cmnd",
    "phone",
    "email",
    "tax_code",
    "bank_account",
    "card_number",
    "address",
)


class ControlRefs:
    def __init__(
        self,
        catalogue: RefCatalogue,
        *,
        risks: Callable[[], Iterable[str]] | None = None,
        rule_scopes: Callable[[], Mapping[str, Any]] | None = None,
        detectors: Iterable[str] = DETECTOR_SLUGS,
    ) -> None:
        self.catalogue = catalogue
        self._risks = risks
        self._rule_scopes = rule_scopes
        self._detectors = frozenset(detectors)
        self._cache: dict[str, Any] = {}

    def clear(self) -> None:
        """Forget cached lookups (call at the start of an operation)."""
        self.catalogue.clear()
        self._cache.clear()

    def risk_ids(self) -> frozenset[str]:
        if "risk" not in self._cache:
            self._cache["risk"] = frozenset(self._risks()) if self._risks else frozenset()
        return self._cache["risk"]

    def rule_ids(self) -> frozenset[str]:
        return self.catalogue.rule_ids()

    def scopes(self) -> Mapping[str, Any]:
        """rule id -> ``"*"`` or a list of agent ids (``agent_scope`` of the rule)."""
        if "scopes" not in self._cache:
            self._cache["scopes"] = dict(self._rule_scopes()) if self._rule_scopes else {}
        return self._cache["scopes"]

    def exists(self, kind: str, target: str) -> bool:
        if kind not in MAP_KINDS:
            return False
        if kind == "risk":
            return target in self.risk_ids()
        if kind == "detector":
            return target in self._detectors
        if kind == "document":
            return True  # a bank document: the shape is checked by check_target
        return self.catalogue.exists(kind, target)

    def check(self, kind: str, target: str) -> None:
        """ControlError when the target does not exist."""
        if not self.exists(kind, target):
            hint = (
                "; import the risks first: python -m supervisor.risk import config/risks"
                if kind == "risk"
                else ""
            )
            raise ControlError(f"{kind} {target!r} does not exist{hint}")

    def rule_applies(self, rule_id: str, agent_id: str) -> bool:
        """True when the rule is in scope for the agent (or its scope is unknown)."""
        scope = self.scopes().get(rule_id)
        if scope in (None, "*"):
            return True
        return agent_id.lower() in {str(a).lower() for a in scope}


def build_refs(state: Any, settings: Any) -> ControlRefs:
    """The catalogue over the live store and the repo files (lazy: nothing is read until used)."""
    base = build_catalogue(state, settings)

    def risks() -> list[str]:
        try:
            return [str(r["risk_id"]) for r in state.query("risk") if r["status"] != "retired"]
        except Exception:  # noqa: BLE001 - an old store without the WP29 tables
            return []

    def scopes() -> dict[str, Any]:
        out: dict[str, Any] = {}
        deployed = False
        for r in state.query("rule"):
            if r.get("effective_to") is not None:
                continue
            raw = str(r.get("agent_scope") or "*")
            out[str(r["rule_id"])] = "*" if raw == "*" else [x for x in raw.split(",") if x]
            deployed = True
        if deployed:
            return out
        from supervisor.config import REPO_ROOT
        from supervisor.gateway.policy import load_policy_dir

        folder = getattr(settings, "policy_dir", None) or (REPO_ROOT / "policies")
        return {r.id: r.agent_scope for r in load_policy_dir(folder).doc.rules}

    return ControlRefs(base, risks=risks, rule_scopes=scopes)


def runtime_sources(state: Any, control_id: str) -> list[tuple[str, str]]:
    """(kind, target) runtime evidence sources of an ACTIVE control; ``[]`` for a draft, a
    retired, a bank-owned or an unknown control. This is the expander the WP29 ``Collector``
    calls for a ``control`` link, so a risk sees a control through the facts the control itself
    uses (a bank control never shows working, so it gives a risk no evidence either)."""
    row = state.get("control", {"control_id": control_id})
    if row is None or row["status"] != "active" or row.get("implemented_by") == "bank":
        return []
    return sorted(
        (str(r["kind"]), str(r["target"]))
        for r in state.query("control_map", {"control_id": control_id})
        if _on(r["active"]) and r["kind"] in RUNTIME_KINDS
    )


def control_scope(state: Any, control_id: str) -> list[str]:
    """The agents a control applies to: ``["*"]`` or a list of lower-case agent ids."""
    import json

    row = state.get("control", {"control_id": control_id})
    if row is None:
        return []
    raw = row.get("scope_agents")
    try:
        value = raw if isinstance(raw, list) else json.loads(raw or '["*"]')
    except (TypeError, ValueError):
        return ["*"]
    return [str(x).lower() if x != "*" else "*" for x in value] or ["*"]


def map_fingerprint(state: Any, control_id: str) -> str:
    """Short hash of what decides the evidence of a control: its status, who implements it, its
    agents and its whole active map. Any change gives another value, so old evidence stops
    counting."""
    from supervisor.core.canonical import sha256_hex

    row = state.get("control", {"control_id": control_id})
    if row is None:
        return "gone"
    maps = sorted(
        f"{r['kind']}:{r['target']}"
        for r in state.query("control_map", {"control_id": control_id})
        if _on(r["active"])
    )
    return sha256_hex(
        [row["status"], str(row.get("implemented_by")), str(row.get("scope_agents")), maps]
    )[:16]


def _on(value: Any) -> bool:
    if isinstance(value, str):
        return value.strip().lower() in ("1", "true")
    return bool(value)

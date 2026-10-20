"""Resolve the per-agent monitor bindings (WP1b-B, D06; docs/monitors.md).

Order for every field, first hit wins:

1. ``policies/*.yaml``  ``agents.<id>.monitors``  (the policy is the control surface),
2. the agent manifest ``monitors:`` key,
3. derived from the tool risk classes (a ``credit`` tool is the fairness decision; a single
   ``money`` tool, or one called ``transfer``, feeds the split-payment scan; a non-money tool
   named like ``reply`` / ``response`` / ``memo`` is the quality output),
4. nothing: the monitor cannot run for this agent. ``gap`` then holds the reason, and the
   monitor writes a ``not_applicable`` status (``monitors/status.py``) instead of staying
   silent.

Tool classes come from the manifest tools, the ``tools:`` map of the policy files and the
tool names the agent was seen calling (``observed``). No network, no database.
"""

from __future__ import annotations

import logging
import re
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml
from pydantic import ValidationError

from supervisor.config import REPO_ROOT
from supervisor.core.errors import ConfigError
from supervisor.core.monitor_bindings import (
    DriftBinding,
    FairnessBinding,
    MonitorBindings,
    QualityBinding,
    SplitPaymentBinding,
)

log = logging.getLogger("supervisor.monitors")

DEFAULT_POLICY_DIR = REPO_ROOT / "policies"
DEFAULT_MANIFEST_ROOT = REPO_ROOT / "src" / "supervisor_agents"
_REPLY_NAME = re.compile(r"(^|_)(reply|respond|response|answer|message|memo)(_|$)")
_NOT_OUTPUT_CLASSES = frozenset({"money", "credit", "pii_export"})

# Source labels written next to a resolved value.
POLICY, MANIFEST, DERIVED, DEFAULT, NONE = "policy", "manifest", "derived", "default", "none"


@dataclass(frozen=True)
class QualityResolved:
    reply_tools: tuple[str, ...] = ()
    text_arg: str = "text"
    source: str = NONE
    gap: str | None = "no reply tool bound or derivable"

    @property
    def bound(self) -> bool:
        return bool(self.reply_tools)


@dataclass(frozen=True)
class FairnessResolved:
    decision_tool: str | None = None
    decision_arg: str | None = None  # None = use the global fairness config
    subject_arg: str | None = None
    approve_values: tuple[str, ...] = ()
    protected_attribute_keys: Mapping[str, str] = field(default_factory=dict)
    source: str = NONE
    gap: str | None = "no decision tool bound or derivable"

    @property
    def bound(self) -> bool:
        return self.decision_tool is not None


@dataclass(frozen=True)
class SplitResolved:
    tool: str | None = None
    customer_key: str | None = None  # None = default of SplitPaymentConfig
    payee_key: str | None = None
    source: str = NONE
    gap: str | None = "no money tool bound or derivable"

    @property
    def bound(self) -> bool:
        return self.tool is not None


@dataclass(frozen=True)
class Resolved:
    agent_id: str
    quality: QualityResolved
    fairness: FairnessResolved
    split: SplitResolved
    drift: DriftBinding | None
    tools: Mapping[str, str]  # tool name -> risk class known for the agent


@dataclass
class _AgentInfo:
    tools: dict[str, str] = field(default_factory=dict)
    manifest: MonitorBindings | None = None
    policy: MonitorBindings | None = None


def _parse(raw: Any, where: str) -> MonitorBindings | None:
    if not raw:
        return None
    try:
        return MonitorBindings.model_validate(raw)
    except ValidationError as exc:
        first = exc.errors()[0]
        loc = ".".join(str(x) for x in first["loc"])
        raise ConfigError(f"{where}: monitors.{loc}: {first['msg']}") from exc


class BindingResolver:
    """Reads manifests and policy files once; ``resolve(agent_id)`` is then pure."""

    def __init__(
        self,
        *,
        manifest_roots: Sequence[Path] = (DEFAULT_MANIFEST_ROOT,),
        policy_dirs: Sequence[Path] = (DEFAULT_POLICY_DIR,),
    ) -> None:
        self._agents: dict[str, _AgentInfo] = {}
        self._policy_tools: dict[str, str] = {}
        for root in manifest_roots:
            self._load_manifests(Path(root))
        for d in policy_dirs:
            self._load_policies(Path(d))

    @classmethod
    def from_settings(cls, settings: Any) -> BindingResolver:
        roots = [DEFAULT_MANIFEST_ROOT]
        extra = getattr(settings, "monitor_manifest_dir", None)
        if extra:
            roots.append(_abs(extra))
        pdirs = [DEFAULT_POLICY_DIR]
        extra_p = getattr(settings, "monitor_policy_dir", None)
        if extra_p:
            pdirs.append(_abs(extra_p))
        return cls(manifest_roots=roots, policy_dirs=pdirs)

    # -- loading ---------------------------------------------------------------
    def _info(self, agent_id: str) -> _AgentInfo:
        return self._agents.setdefault(agent_id, _AgentInfo())

    def _load_manifests(self, root: Path) -> None:
        if not root.is_dir():
            return
        for path in sorted(root.glob("*/manifest.yaml")):
            try:
                doc = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
            except (OSError, yaml.YAMLError) as exc:
                raise ConfigError(f"monitor bindings: manifest {path.name}: {exc}") from exc
            if not isinstance(doc, Mapping):
                continue
            agent_id = str(doc.get("id") or path.parent.name)
            info = self._info(agent_id)
            for t in doc.get("tools") or []:
                if isinstance(t, Mapping) and t.get("name"):
                    info.tools[str(t["name"])] = str(t.get("risk_class") or "read_only")
            info.manifest = _parse(doc.get("monitors"), f"manifest {agent_id}")

    def _load_policies(self, directory: Path) -> None:
        if not directory.is_dir():
            return
        for path in sorted(directory.glob("*.yaml")):
            try:
                doc = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
            except (OSError, yaml.YAMLError) as exc:
                raise ConfigError(f"monitor bindings: policy {path.name}: {exc}") from exc
            if not isinstance(doc, Mapping):
                continue
            for name, cls in (doc.get("tools") or {}).items():
                self._policy_tools.setdefault(str(name), str(cls))
            for agent_id, entry in (doc.get("agents") or {}).items():
                if isinstance(entry, Mapping) and entry.get("monitors"):
                    self._info(str(agent_id)).policy = _parse(
                        entry["monitors"], f"policy {path.name} agent {agent_id}"
                    )
                else:
                    self._info(str(agent_id))

    # -- reads -----------------------------------------------------------------
    def agent_ids(self) -> list[str]:
        return sorted(self._agents)

    def tool_classes(self, agent_id: str, observed: Iterable[str] = ()) -> dict[str, str]:
        tools = dict(self._agents.get(agent_id, _AgentInfo()).tools)
        for name in observed:
            tools.setdefault(str(name), self._policy_tools.get(str(name), "read_only"))
        return tools

    def resolve(self, agent_id: str, observed: Iterable[str] = ()) -> Resolved:
        info = self._agents.get(agent_id, _AgentInfo())
        tools = self.tool_classes(agent_id, observed)
        layers = [(POLICY, info.policy), (MANIFEST, info.manifest)]
        return Resolved(
            agent_id=agent_id,
            quality=_quality(layers, tools),
            fairness=_fairness(layers, tools),
            split=_split(layers, tools),
            drift=_drift(layers),
            tools=tools,
        )


def _abs(path: Any) -> Path:
    p = Path(path).expanduser()
    return p if p.is_absolute() else REPO_ROOT / p


def _pick(layers: Sequence[tuple[str, MonitorBindings | None]], attr: str) -> tuple[str, Any]:
    for source, b in layers:
        if b is not None and getattr(b, attr) is not None:
            return source, getattr(b, attr)
    return NONE, None


def _quality(
    layers: Sequence[tuple[str, MonitorBindings | None]], tools: Mapping[str, str]
) -> QualityResolved:
    source, b = _pick(layers, "quality")
    if isinstance(b, QualityBinding) and b.reply_tools:
        return QualityResolved(tuple(b.reply_tools), b.text_arg, source, None)
    derived = sorted(
        n for n, c in tools.items() if c not in _NOT_OUTPUT_CLASSES and _REPLY_NAME.search(n)
    )
    if derived:
        text_arg = b.text_arg if isinstance(b, QualityBinding) else "text"
        return QualityResolved(tuple(derived), text_arg, DERIVED, None)
    return QualityResolved(
        gap="no reply tool bound (monitors.quality.reply_tools) and none derivable from tool names"
    )


def _fairness(
    layers: Sequence[tuple[str, MonitorBindings | None]], tools: Mapping[str, str]
) -> FairnessResolved:
    source, b = _pick(layers, "fairness")
    if isinstance(b, FairnessBinding) and b.decision_tool:
        return FairnessResolved(
            b.decision_tool,
            b.decision_arg,
            b.subject_arg,
            tuple(b.approve_values),
            dict(b.protected_attribute_keys),
            source,
            None,
        )
    credit = sorted(n for n, c in tools.items() if c == "credit")
    keys = dict(b.protected_attribute_keys) if isinstance(b, FairnessBinding) else {}
    if len(credit) == 1:
        extra = (b.decision_arg, b.subject_arg, tuple(b.approve_values)) if b else (None, None, ())
        return FairnessResolved(credit[0], extra[0], extra[1], extra[2], keys, DERIVED, None)
    if len(credit) > 1:
        return FairnessResolved(
            gap=f"several credit tools ({', '.join(credit)}): set monitors.fairness.decision_tool"
        )
    return FairnessResolved(
        gap="no decision tool bound (monitors.fairness.decision_tool) and no tool of class credit"
    )


def _split(
    layers: Sequence[tuple[str, MonitorBindings | None]], tools: Mapping[str, str]
) -> SplitResolved:
    source, b = _pick(layers, "split_payment")
    if isinstance(b, SplitPaymentBinding) and b.tool:
        return SplitResolved(b.tool, b.customer_key, b.payee_key, source, None)
    money = sorted(n for n, c in tools.items() if c == "money")
    keys = (b.customer_key, b.payee_key) if isinstance(b, SplitPaymentBinding) else (None, None)
    if len(money) == 1:
        return SplitResolved(money[0], keys[0], keys[1], DERIVED, None)
    if "transfer" in money:  # the demo name wins when a payments agent has several
        return SplitResolved("transfer", keys[0], keys[1], DERIVED, None)
    if money:
        return SplitResolved(
            gap=f"several money tools ({', '.join(money)}): set monitors.split_payment.tool"
        )
    return SplitResolved(
        gap="no payment tool bound (monitors.split_payment.tool) and no tool of class money"
    )


def _drift(layers: Sequence[tuple[str, MonitorBindings | None]]) -> DriftBinding | None:
    _, b = _pick(layers, "drift")
    return b if isinstance(b, DriftBinding) else None


__all__ = [
    "DEFAULT",
    "DERIVED",
    "MANIFEST",
    "NONE",
    "POLICY",
    "BindingResolver",
    "FairnessResolved",
    "QualityResolved",
    "Resolved",
    "SplitResolved",
]

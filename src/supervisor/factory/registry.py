"""Loaders for ``config/factory_tools.yaml`` and ``config/factory_groups.yaml`` (WP-F1).

Strict keys: an unknown key, a wrong type or a value outside the platform vocabulary raises
``RegistryError`` with the file and the field. ``check_definition`` applies the registry to a
validated agent definition (tool ids exist, modes allowed, group allowed, dimension owned).
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from supervisor.config import REPO_ROOT
from supervisor.core.errors import SupervisorError
from supervisor.factory import caps
from supervisor.factory.schemas.agent_definition_v1 import AgentDefinitionV1

TOOLS_PATH = REPO_ROOT / "config" / "factory_tools.yaml"
GROUPS_PATH = REPO_ROOT / "config" / "factory_groups.yaml"
_TOOL_ID = re.compile(r"^[a-z][a-z0-9_-]{0,63}$")


class RegistryError(SupervisorError):
    """A registry file is wrong. The message names the file and the field."""


@dataclass(frozen=True)
class Tool:
    tool_id: str
    label: str
    kind: str
    scope: tuple[str, ...]
    data_class: str
    allowed_groups: tuple[str, ...]
    modes: tuple[str, ...]


@dataclass(frozen=True)
class Group:
    group_id: str
    label: str
    roles: tuple[str, ...]
    dimensions: tuple[str, ...]


@dataclass(frozen=True)
class ToolRegistry:
    tools: tuple[Tool, ...]

    def get(self, tool_id: str) -> Tool | None:
        return next((t for t in self.tools if t.tool_id == tool_id), None)

    def visible_to(self, group_id: str) -> tuple[Tool, ...]:
        return tuple(t for t in self.tools if group_id in t.allowed_groups)


@dataclass(frozen=True)
class GroupRegistry:
    groups: tuple[Group, ...]

    def get(self, group_id: str) -> Group | None:
        return next((g for g in self.groups if g.group_id == group_id), None)

    def owner_of(self, dimension_id: str) -> Group | None:
        return next((g for g in self.groups if dimension_id in g.dimensions), None)


def _read(path: Path) -> Mapping[str, Any]:
    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as exc:
        raise RegistryError(f"{path.name}: cannot read the file ({type(exc).__name__})") from exc
    if not isinstance(raw, Mapping):
        raise RegistryError(f"{path.name}: must be an object")
    return raw


def _strict(item: Any, allowed: tuple[str, ...], where: str) -> Mapping[str, Any]:
    if not isinstance(item, Mapping):
        raise RegistryError(f"{where}: must be an object")
    unknown = sorted(str(k) for k in set(item) - set(allowed))
    if unknown:
        raise RegistryError(f"{where}: unknown key: {', '.join(unknown)}")
    missing = sorted(k for k in allowed if k not in item)
    if missing:
        raise RegistryError(f"{where}: missing key: {', '.join(missing)}")
    return item


def _text(value: Any, where: str, limit: int = 200) -> str:
    if not isinstance(value, str) or not value.strip() or len(value) > limit:
        raise RegistryError(f"{where}: must be text of 1 to {limit} characters")
    return value.strip()


def _enum_list(value: Any, vocab: tuple[str, ...], where: str) -> tuple[str, ...]:
    if not isinstance(value, list) or not value:
        raise RegistryError(f"{where}: must be a non-empty list")
    out: list[str] = []
    for v in value:
        if v not in vocab:
            raise RegistryError(f"{where}: {v!r} is not one of {', '.join(vocab)}")
        if v in out:
            raise RegistryError(f"{where}: {v!r} appears twice")
        out.append(v)
    return tuple(out)


def _header(raw: Mapping[str, Any], key: str, name: str) -> list[Any]:
    _strict_top = {"version", key}
    unknown = sorted(str(k) for k in set(raw) - _strict_top)
    if unknown:
        raise RegistryError(f"{name}: unknown key: {', '.join(unknown)}")
    if raw.get("version") != 1:
        raise RegistryError(f"{name}: version must be 1")
    items = raw.get(key)
    if not isinstance(items, list) or not items:
        raise RegistryError(f"{name}: {key} must be a non-empty list")
    return items


def load_tools(path: Path | None = None) -> ToolRegistry:
    path = path or TOOLS_PATH
    raw = _read(path)
    tools: list[Tool] = []
    for i, item in enumerate(_header(raw, "tools", path.name)):
        where = f"{path.name}: tools[{i}]"
        item = _strict(
            item,
            ("tool_id", "label", "kind", "scope", "data_class", "allowed_groups", "modes"),
            where,
        )
        tool_id = _text(item["tool_id"], f"{where}.tool_id", 64)
        if not _TOOL_ID.match(tool_id):
            raise RegistryError(f"{where}.tool_id: lowercase letters, digits, _ and - only")
        if any(t.tool_id == tool_id for t in tools):
            raise RegistryError(f"{where}.tool_id: {tool_id} is defined twice")
        kind = item["kind"]
        if kind not in caps.TOOL_KINDS:
            raise RegistryError(
                f"{where}.kind: {kind!r} is not one of {', '.join(caps.TOOL_KINDS)}"
            )
        data_class = item["data_class"]
        if data_class not in caps.DATA_CLASSES:
            raise RegistryError(
                f"{where}.data_class: {data_class!r} is not one of {', '.join(caps.DATA_CLASSES)}"
            )
        tools.append(
            Tool(
                tool_id=tool_id,
                label=_text(item["label"], f"{where}.label"),
                kind=kind,
                scope=_enum_list(item["scope"], caps.SCOPE_KINDS, f"{where}.scope"),
                data_class=data_class,
                allowed_groups=_enum_list(
                    item["allowed_groups"], caps.GROUPS, f"{where}.allowed_groups"
                ),
                modes=_enum_list(item["modes"], caps.TOOL_MODES, f"{where}.modes"),
            )
        )
    return ToolRegistry(tuple(tools))


def load_groups(path: Path | None = None) -> GroupRegistry:
    path = path or GROUPS_PATH
    raw = _read(path)
    groups_raw = raw.get("groups")
    if not isinstance(groups_raw, Mapping) or not groups_raw:
        raise RegistryError(f"{path.name}: groups must be a non-empty object")
    if raw.get("version") != 1:
        raise RegistryError(f"{path.name}: version must be 1")
    unknown = sorted(str(k) for k in set(raw) - {"version", "groups"})
    if unknown:
        raise RegistryError(f"{path.name}: unknown key: {', '.join(unknown)}")
    groups: list[Group] = []
    owned: dict[str, str] = {}
    for gid, item in groups_raw.items():
        where = f"{path.name}: groups.{gid}"
        if gid not in caps.GROUPS:
            raise RegistryError(f"{where}: not a platform group ({', '.join(caps.GROUPS)})")
        item = _strict(item, ("label", "roles", "dimensions"), where)
        dims = _enum_list(item["dimensions"], caps.DIMENSIONS, f"{where}.dimensions")
        for d in dims:
            if d in owned:
                raise RegistryError(f"{where}.dimensions: {d} is already owned by {owned[d]}")
            owned[d] = gid
        groups.append(
            Group(
                group_id=gid,
                label=_text(item["label"], f"{where}.label"),
                roles=_enum_list(item["roles"], caps.ROLES, f"{where}.roles"),
                dimensions=dims,
            )
        )
    return GroupRegistry(tuple(groups))


def check_definition(
    defn: AgentDefinitionV1, tools: ToolRegistry, groups: GroupRegistry
) -> list[tuple[str, str]]:
    """Registry checks of a validated definition. Returns ``(field, message)`` pairs."""
    errors: list[tuple[str, str]] = []
    group = groups.get(defn.owner_group)
    if group is None:
        errors.append(("owner_group", f"{defn.owner_group} is not in factory_groups.yaml"))
    elif defn.dimension_id not in group.dimensions:
        errors.append(
            ("dimension_id", f"group {defn.owner_group} does not own dimension {defn.dimension_id}")
        )
    for i, ref in enumerate(defn.tools):
        field = f"tools[{i}]"
        tool = tools.get(ref.tool_id)
        if tool is None:
            errors.append((f"{field}.tool_id", f"{ref.tool_id} is not in factory_tools.yaml"))
            continue
        if defn.owner_group not in tool.allowed_groups:
            errors.append(
                (f"{field}.tool_id", f"group {defn.owner_group} may not use {ref.tool_id}")
            )
        if ref.mode not in tool.modes:
            errors.append((f"{field}.mode", f"{ref.tool_id} does not allow mode {ref.mode}"))
        if ref.scope is not None:
            kind = ref.scope.split(":", 1)[0]
            if kind not in tool.scope:
                errors.append(
                    (f"{field}.scope", f"scope kind {kind!r} is not one of {', '.join(tool.scope)}")
                )
    return errors

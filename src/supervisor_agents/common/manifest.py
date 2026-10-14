"""Agent manifest: identity, owner, risk tier, model family and tools with risk classes."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Literal

import yaml

from supervisor.core.models import Agent, AgentVersion

RiskClass = Literal["money", "credit", "pii_export", "read_only"]
RISK_CLASSES: tuple[str, ...] = ("money", "credit", "pii_export", "read_only")
FAIL_CLOSED_CLASSES: frozenset[str] = frozenset({"money", "credit", "pii_export"})
PACKAGE_DIR = Path(__file__).resolve().parents[1]


@dataclass(frozen=True)
class ToolSpec:
    name: str
    risk_class: RiskClass
    description: str
    args: dict[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class AgentManifest:
    id: str
    name: str
    version: str
    owner: str
    owner_user: str
    risk_tier: str
    model_family: str
    model_id: str
    host_type: str
    plug_point: str
    description: str
    tools: tuple[ToolSpec, ...]
    limits: dict[str, int] = field(default_factory=dict)

    def tool(self, name: str) -> ToolSpec | None:
        return next((t for t in self.tools if t.name == name), None)

    @property
    def tool_names(self) -> tuple[str, ...]:
        return tuple(t.name for t in self.tools)

    def tool_manifest_hash(self) -> str:
        # Arg specs are type names ("integer"), not money values, so plain sorted JSON.
        spec = [{"name": t.name, "risk_class": t.risk_class, "args": t.args} for t in self.tools]
        text = json.dumps(spec, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
        return hashlib.sha256(text.encode("utf-8")).hexdigest()

    def agent_row(self, now: datetime) -> Agent:
        return Agent(
            agent_id=self.id,
            name=self.name,
            owner_team=self.owner,
            owner_user=self.owner_user,
            risk_tier=self.risk_tier,  # type: ignore[arg-type]
            host_type=self.host_type,
            plug_point=self.plug_point,
            model_family=self.model_family,
            created_at=now,
        )

    def version_row(self, now: datetime, prompt_hash: str | None = None) -> AgentVersion:
        return AgentVersion(
            agent_id=self.id,
            version=self.version,
            prompt_hash=prompt_hash,
            tool_manifest_hash=self.tool_manifest_hash(),
            model_endpoint=self.model_id,
            model_family=self.model_family,
            deployed_at=now,
        )


def parse_manifest(data: dict[str, Any]) -> AgentManifest:
    tools = []
    for t in data["tools"]:
        if t["risk_class"] not in RISK_CLASSES:
            raise ValueError(f"tool {t['name']}: unknown risk_class {t['risk_class']!r}")
        tools.append(
            ToolSpec(
                name=t["name"],
                risk_class=t["risk_class"],
                description=" ".join(str(t.get("description", "")).split()),
                args={k: str(v) for k, v in (t.get("args") or {}).items()},
            )
        )
    limits = {k: int(v) for k, v in (data.get("limits") or {}).items()}
    return AgentManifest(
        id=data["id"],
        name=data["name"],
        version=str(data["version"]),
        owner=data["owner"],
        owner_user=data["owner_user"],
        risk_tier=data["risk_tier"],
        model_family=data["model_family"],
        model_id=data["model_id"],
        host_type=data["host_type"],
        plug_point=data["plug_point"],
        description=" ".join(str(data.get("description", "")).split()),
        tools=tuple(tools),
        limits=limits,
    )


def load_manifest(agent_id: str) -> AgentManifest:
    path = PACKAGE_DIR / agent_id / "manifest.yaml"
    with path.open(encoding="utf-8") as fh:
        return parse_manifest(yaml.safe_load(fh))

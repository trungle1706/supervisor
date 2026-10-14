"""Capture levels per agent (digest / masked / raw).

* ``digest``: tool name, args hash, amount (integer minor units), status. No text at all.
* ``masked``: as digest, plus args and result text after the Masker ran.
* ``raw``: as masked, plus the unmasked text in the restricted ``agent_event_raw`` table.
  Allowed only when the agent manifest says ``capture: {raw_allowed: true}``.

The manifest sets the level (``capture: {level: masked}``). A span may ask for a LOWER
level with the ``supervisor.capture_level`` attribute; it can never raise it. With no
Masker configured, ``masked`` and ``raw`` fall back to ``digest`` (fail safe: no text).
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

import yaml

CaptureLevel = Literal["digest", "masked", "raw"]
LEVELS: tuple[CaptureLevel, ...] = ("digest", "masked", "raw")
_RANK = {name: i for i, name in enumerate(LEVELS)}
AGENTS_DIR = Path(__file__).resolve().parents[2] / "supervisor_agents"


def lower(a: str, b: str) -> CaptureLevel:
    """The lower (more private) of two levels. Unknown names count as digest."""
    return LEVELS[min(_RANK.get(a, 0), _RANK.get(b, 0))]


@dataclass(frozen=True)
class AgentCapture:
    level: CaptureLevel = "masked"
    raw_allowed: bool = False

    @property
    def max_level(self) -> CaptureLevel:
        if self.level == "raw" and not self.raw_allowed:
            return "masked"
        return self.level


def capture_from_manifest(data: Mapping[str, Any]) -> AgentCapture:
    """Read the ``capture`` block of an agent manifest dict. Bad values raise ValueError."""
    block = data.get("capture") or {}
    if not isinstance(block, Mapping):
        raise ValueError("manifest capture must be a mapping")
    level = str(block.get("level", "masked"))
    if level not in LEVELS:
        raise ValueError(f"manifest capture.level must be one of {LEVELS}, got {level!r}")
    raw_allowed = block.get("raw_allowed", False)
    if not isinstance(raw_allowed, bool):
        raise ValueError("manifest capture.raw_allowed must be true or false")
    if level == "raw" and not raw_allowed:
        raise ValueError("manifest capture.level raw needs capture.raw_allowed: true")
    return AgentCapture(level, raw_allowed)  # type: ignore[arg-type]


@dataclass(frozen=True)
class CapturePolicy:
    """Capture level per agent id. Agents not listed get ``default`` (never raw)."""

    agents: Mapping[str, AgentCapture] = field(default_factory=dict)
    default: CaptureLevel = "masked"

    def for_agent(self, agent_id: str) -> AgentCapture:
        found = self.agents.get(agent_id)
        if found is not None:
            return found
        return AgentCapture(lower(self.default, "masked"), False)

    def effective(self, agent_id: str, requested: str | None, has_masker: bool) -> CaptureLevel:
        """Level used for one span: manifest level, lowered by the span's request,
        and digest when no Masker is configured."""
        level = self.for_agent(agent_id).max_level
        if requested:
            level = lower(level, requested)
        if not has_masker:
            return "digest"
        return level

    @classmethod
    def from_manifests(
        cls, manifests: Iterable[Mapping[str, Any]], default: CaptureLevel = "masked"
    ) -> CapturePolicy:
        return cls({str(m["id"]): capture_from_manifest(m) for m in manifests}, default)

    @classmethod
    def digest_only(cls) -> CapturePolicy:
        return cls({}, "digest")


def load_manifest_policy(
    root: Path = AGENTS_DIR, default: CaptureLevel = "masked"
) -> CapturePolicy:
    """Policy from every ``<root>/*/manifest.yaml`` (the demo agents by default)."""
    found = []
    for path in sorted(root.glob("*/manifest.yaml")):
        with path.open(encoding="utf-8") as fh:
            data = yaml.safe_load(fh)
        if isinstance(data, Mapping) and "id" in data:
            found.append(data)
    return CapturePolicy.from_manifests(found, default)

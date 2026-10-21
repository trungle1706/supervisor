"""``config/detectors.yaml`` and the per-agent override from the policy file (WP37).

Resolution order for one detector on one call, strongest first:

1. ``agents.<id>.detectors.settings.<slug>`` in the policy file (a per-agent value),
2. ``agents.<id>.detectors.preset`` (a per-agent default preset),
3. ``detectors.<slug>`` in ``config/detectors.yaml``,
4. ``default_preset`` in ``config/detectors.yaml``, then the detector's own defaults.

``enable`` / ``disable`` in the agent override switch single detectors; ``skip_tools`` lists tools
for which the gate does not run detectors at all (status ``skip``, a deterministic policy value).
"""

from __future__ import annotations

import logging
from collections.abc import Mapping
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from supervisor.core.detectors import DetectorRegistry, DetectorSetting, RunConfig
from supervisor.core.errors import ConfigError
from supervisor.gateway.policy import AgentDetectors

log = logging.getLogger(__name__)

MAX_CONFIG_BYTES = 64 * 1024
PRESET_NAMES = ("strict", "balanced", "lenient")
RISK = ("money", "credit", "pii_export", "read_only")


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class DetectorEntry(_Strict):
    enabled: bool = True
    fail_closed: bool = True
    preset: str | None = None
    settings: dict[str, Any] = Field(default_factory=dict)


class Limits(_Strict):
    max_payload_chars: int = Field(default=100_000, ge=1_000, le=5_000_000)
    timeout_ms: int = Field(default=500, ge=10, le=60_000)
    fail_closed_risk_classes: list[str] = Field(default_factory=lambda: list(RISK[:3]))


class DetectorsFile(_Strict):
    version: int = 1
    default_preset: str = "balanced"
    limits: Limits = Field(default_factory=Limits)
    detectors: dict[str, DetectorEntry] = Field(default_factory=dict)


def parse_config(text: str, source: str = "<text>") -> DetectorsFile:
    if len(text.encode("utf-8")) > MAX_CONFIG_BYTES:
        raise ConfigError(f"{source}: larger than {MAX_CONFIG_BYTES} bytes")
    try:
        data = yaml.safe_load(text)
    except yaml.YAMLError as exc:
        raise ConfigError(f"{source}: not valid YAML: {exc}") from exc
    if data is None:
        data = {}
    if not isinstance(data, Mapping):
        raise ConfigError(f"{source}: top level must be a mapping")
    try:
        return DetectorsFile.model_validate(data)
    except ValidationError as exc:
        msgs = "; ".join(
            f"{'.'.join(str(p) for p in e['loc'])}: {e['msg']}" for e in exc.errors()[:10]
        )
        raise ConfigError(f"{source}: {msgs}") from exc


def load_config(path: Path | str) -> DetectorsFile:
    p = Path(path)
    if not p.is_file():
        raise ConfigError(f"detectors config not found: {p}")
    return parse_config(p.read_text(encoding="utf-8"), p.name)


class ResolvedDetectors:
    """The file checked against the catalogue, ready to resolve per call."""

    def __init__(self, cfg: DetectorsFile, registry: DetectorRegistry) -> None:
        self.cfg = cfg
        self.registry = registry
        problems: list[str] = []
        if cfg.default_preset not in PRESET_NAMES:
            problems.append(f"default_preset {cfg.default_preset!r}")
        bad_risk = [r for r in cfg.limits.fail_closed_risk_classes if r not in RISK]
        if bad_risk:
            problems.append(f"limits.fail_closed_risk_classes {bad_risk}")
        for slug, entry in cfg.detectors.items():
            if slug not in registry:
                problems.append(f"detectors.{slug}: not in the catalogue {registry.slugs}")
                continue
            _, errs = registry.validate_settings(slug, self._merged(slug, entry, None, None))
            problems += [f"detectors.{slug}.{e}" for e in errs]
            if entry.fail_closed and not registry.may_fail_closed(slug):
                # R1: an advisory detector never fails closed; the value is ignored, loudly.
                log.warning(
                    "detectors.%s.fail_closed: ignored (advisory detector or no approval, R1)", slug
                )
        if problems:
            raise ConfigError("detectors config invalid: " + "; ".join(problems))
        self._base = RunConfig(
            detectors={},
            max_payload_chars=cfg.limits.max_payload_chars,
            timeout_ms=cfg.limits.timeout_ms,
            fail_closed_risk_classes=frozenset(cfg.limits.fail_closed_risk_classes),
        )

    def _merged(
        self,
        slug: str,
        entry: DetectorEntry,
        agent: AgentDetectors | None,
        agent_preset: str | None,
    ) -> dict[str, Any]:
        values: dict[str, Any] = dict(entry.settings)
        preset = entry.preset or self.cfg.default_preset
        if agent_preset:
            preset = agent_preset
        values["preset"] = values.get("preset") or preset
        if agent is not None and slug in agent.settings:
            values.update(agent.settings[slug])
            if "preset" not in agent.settings[slug] and agent_preset:
                values["preset"] = agent_preset
        return values

    def for_agent(self, agent: AgentDetectors | None) -> tuple[RunConfig, frozenset[str]]:
        """(run config, skip_tools) for one agent. An unknown slug in the override is ignored
        here (it is reported by :meth:`check_agent` when the policy loads)."""
        enabled_extra = set(agent.enable) if agent else set()
        disabled = set(agent.disable) if agent else set()
        agent_preset = agent.preset if agent else None
        out: dict[str, DetectorSetting] = {}
        for slug in self.registry.slugs:
            entry = self.cfg.detectors.get(slug, DetectorEntry(enabled=False))
            on = (entry.enabled or slug in enabled_extra) and slug not in disabled
            out[slug] = DetectorSetting(
                enabled=on,
                settings=self._merged(slug, entry, agent, agent_preset),
                fail_closed=entry.fail_closed and self.registry.may_fail_closed(slug),
            )
        run = RunConfig(
            detectors=out,
            max_payload_chars=self._base.max_payload_chars,
            timeout_ms=self._base.timeout_ms,
            fail_closed_risk_classes=self._base.fail_closed_risk_classes,
        )
        return run, frozenset(agent.skip_tools) if agent else frozenset()

    def check_agent(self, agent_id: str, agent: AgentDetectors) -> list[str]:
        """Problems in one agent's override (unknown slug, bad value). Empty = fine."""
        problems = []
        if agent.preset is not None and agent.preset not in PRESET_NAMES:
            problems.append(f"{agent_id}: preset {agent.preset!r}")
        for slug in [*agent.enable, *agent.disable, *agent.settings]:
            if slug not in self.registry:
                problems.append(f"{agent_id}: detector {slug!r} is not in the catalogue")
        for slug in agent.settings:
            if slug in self.registry:
                entry = self.cfg.detectors.get(slug, DetectorEntry())
                _, errs = self.registry.validate_settings(
                    slug, self._merged(slug, entry, agent, agent.preset)
                )
                problems += [f"{agent_id}: {slug}.{e}" for e in errs]
        return problems

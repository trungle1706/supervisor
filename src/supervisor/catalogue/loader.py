"""Load the capability catalogue and derive ``coverage`` rows.

    cat = load_catalogue()                       # built-in manifests
    cat = load_catalogue(extra_dirs=[bank_dir])  # plus a bank's own manifests
    picked = cat.select({"money", "read_only"}, features, plug_point="gate_hook")
    rows = coverage_rows("payments", cat, picked)

A ``coverage`` row says, per agent and capability, whether the capability is on and,
when it is off, why. Rows derive only from which manifests are selected.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml
from pydantic import ValidationError

from supervisor.catalogue.model import CapabilityManifest
from supervisor.core.errors import SupervisorError

MANIFEST_DIR = Path(__file__).resolve().parent / "manifests"
MAX_MANIFEST_BYTES = 32 * 1024


class CatalogueError(SupervisorError):
    """A capability manifest is invalid."""


@dataclass(frozen=True)
class Selection:
    """Result of selecting capabilities for one agent."""

    on: tuple[CapabilityManifest, ...]
    off: tuple[tuple[CapabilityManifest, str], ...]  # (manifest, reason)

    @property
    def on_ids(self) -> list[str]:
        return [m.id for m in self.on]


@dataclass
class Catalogue:
    manifests: dict[str, CapabilityManifest] = field(default_factory=dict)

    def __len__(self) -> int:
        return len(self.manifests)

    def get(self, capability_id: str) -> CapabilityManifest:
        try:
            return self.manifests[capability_id]
        except KeyError as exc:
            raise CatalogueError(f"unknown capability {capability_id}") from exc

    def ids(self) -> list[str]:
        return sorted(self.manifests)

    def select(
        self,
        risk_classes: Iterable[str],
        features: Iterable[str],
        plug_point: str = "gate_hook",
    ) -> Selection:
        """Pick capabilities for an agent with these tool risk classes and features."""
        classes = set(risk_classes)
        feats = set(features)
        on: list[CapabilityManifest] = []
        off: list[tuple[CapabilityManifest, str]] = []
        for cid in self.ids():
            m = self.manifests[cid]
            reason = _off_reason(m, classes, feats, plug_point)
            if reason is None:
                on.append(m)
            else:
                off.append((m, reason))
        return Selection(tuple(on), tuple(off))


def _off_reason(
    m: CapabilityManifest, classes: set[str], feats: set[str], plug_point: str
) -> str | None:
    if plug_point not in m.plug_points:
        return f"plug point {plug_point} not supported (needs one of {sorted(m.plug_points)})"
    if m.always_on:
        return None
    if not classes & set(m.applies_to):
        return f"no tool with risk class in {sorted(m.applies_to)}"
    missing = sorted(set(m.requires) - feats)
    if missing:
        return f"agent lacks required features: {missing}"
    return None


def parse_manifest_text(text: str, source: str = "<text>") -> CapabilityManifest:
    if len(text.encode("utf-8")) > MAX_MANIFEST_BYTES:
        raise CatalogueError(f"{source}: manifest larger than {MAX_MANIFEST_BYTES} bytes")
    try:
        data = yaml.safe_load(text)
    except yaml.YAMLError as exc:
        raise CatalogueError(f"{source}: not valid YAML: {exc}") from exc
    if not isinstance(data, Mapping):
        raise CatalogueError(f"{source}: top level must be a mapping")
    try:
        return CapabilityManifest.model_validate(data)
    except ValidationError as exc:
        msgs = "; ".join(
            f"{'.'.join(str(p) for p in e['loc'])}: {e['msg']}" for e in exc.errors()[:10]
        )
        raise CatalogueError(f"{source}: {msgs}") from exc


def load_catalogue(
    directory: str | Path | None = None, extra_dirs: Sequence[str | Path] = ()
) -> Catalogue:
    """Load every ``*.yaml`` manifest (sorted by name). Duplicate ids fail."""
    cat = Catalogue()
    for d in [Path(directory) if directory else MANIFEST_DIR, *map(Path, extra_dirs)]:
        root = d.resolve()
        for f in sorted(root.glob("*.yaml")):
            if f.stat().st_size > MAX_MANIFEST_BYTES:
                raise CatalogueError(f"{f.name}: manifest larger than {MAX_MANIFEST_BYTES} bytes")
            m = parse_manifest_text(f.read_text(encoding="utf-8"), f.name)
            if m.id in cat.manifests:
                raise CatalogueError(f"{f.name}: capability id {m.id} appears twice")
            cat.manifests[m.id] = m
    if not cat.manifests:
        raise CatalogueError("no capability manifests found")
    return cat


def coverage_rows(
    agent_id: str, selection: Selection, status_on: str = "on"
) -> list[dict[str, Any]]:
    """``coverage`` table rows (agent_id, capability_id, status, reason) for one agent.

    ``status_on`` is ``on`` for capabilities that run, ``planned`` for a monitoring plan
    that is not yet merged and enforced."""
    rows = [
        {"agent_id": agent_id, "capability_id": m.id, "status": status_on, "reason": None}
        for m in selection.on
    ]
    rows += [
        {"agent_id": agent_id, "capability_id": m.id, "status": "off", "reason": reason}
        for m, reason in selection.off
    ]
    return sorted(rows, key=lambda r: r["capability_id"])


def write_coverage(state: Any, rows: Iterable[Mapping[str, Any]]) -> int:
    """Upsert coverage rows into the ``coverage`` state table. Returns rows written."""
    n = 0
    for row in rows:
        key = {"agent_id": row["agent_id"], "capability_id": row["capability_id"]}
        existing = state.get("coverage", key)
        if existing is None:
            state.insert("coverage", dict(row))
        elif existing["status"] != row["status"] or existing.get("reason") != row.get("reason"):
            state.update(
                "coverage",
                key,
                {"status": row["status"], "reason": row.get("reason")},
                int(existing["row_version"]),
            )
        else:
            continue
        n += 1
    return n

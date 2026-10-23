"""Register the candidate agents as AI systems from their manifests (WP-P1).

    python -m supervisor.cli demo seed-systems [--candidates-dir DIR] [--data-dir DIR]

For every folder ``<candidates dir>/<name>/`` that has a ``supervisor.manifest.yaml``:

1. the agent is added to the agent registry when it is not there (owner team, risk tier from
   the highest tool risk class, host type ``app``, plug point, model family; gate state
   SHADOW; one ``agent_registered`` chain record);
2. the AI system is registered with the intake fields of the manifest;
3. the agent is linked to the system;
4. the Decision 33 classification draft is made (never applied: a person applies it).

The command is idempotent: a second run changes nothing. A folder with no manifest, or with an
invalid one, is ``[SKIP]`` with the reason; the other folders still run. Output is ASCII.

Manifest schema (``manifest_version: 1``): see ``docs/deploy/LAUNCH_LAPTOP.md`` section 8.
"""

from __future__ import annotations

import os
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from supervisor.config import Settings
from supervisor.core.errors import SupervisorError, check_agent_id
from supervisor.demo.session import (
    Echo,
    build_session,
    default_echo,
    is_demo_dir,
    mark_demo_dir,
)

MANIFEST_NAME = "supervisor.manifest.yaml"
DEFAULT_CANDIDATES_DIR = Path("~/supervisor-testbed/candidates")
MAX_MANIFEST_BYTES = 256 * 1024

SYSTEM_REQUIRED = (
    "name",
    "owner_user",
    "owner_team",
    "purpose",
    "system_type",
    "org_role",
    "user_segment",
    "personal_data",
    "human_control",
)
SYSTEM_OPTIONAL = ("money_movement", "credit_decision", "business_impact", "autonomy_level")
TOOL_RISK_CLASSES = ("read_only", "pii_export", "money", "credit")
PLUG_POINTS = ("fastapi_middleware", "langgraph_middleware", "sdk")
# Registry risk tier from the highest tool risk class.
TIER_FOR_CLASS = {"read_only": "low", "pii_export": "medium", "money": "high", "credit": "high"}
_TIER_RANK = {"low": 0, "medium": 1, "high": 2, "critical": 3}


class ManifestError(SupervisorError):
    """The manifest is missing or invalid (the folder is skipped)."""


@dataclass(frozen=True)
class Manifest:
    system: dict[str, Any]
    agent_id: str
    agent_name: str
    model_family: str
    plug_point: str
    tools: tuple[tuple[str, str], ...]
    path: Path

    @property
    def risk_tier(self) -> str:
        best = "low"
        for _name, risk_class in self.tools:
            tier = TIER_FOR_CLASS[risk_class]
            if _TIER_RANK[tier] > _TIER_RANK[best]:
                best = tier
        return best


@dataclass
class SeedSystemsReport:
    lines: list[str] = field(default_factory=list)
    ok: bool = True
    systems: dict[str, str] = field(default_factory=dict)  # system name -> system id
    skipped: int = 0
    created: int = 0

    def fail(self, text: str) -> None:
        self.ok = False
        self.lines.append(f"[FAIL] {text}")


def _need_map(raw: Any, what: str) -> Mapping[str, Any]:
    if not isinstance(raw, Mapping):
        raise ManifestError(f"{what} must be a mapping")
    return raw


def _need_text(m: Mapping[str, Any], key: str, what: str) -> str:
    value = m.get(key)
    if not isinstance(value, str) or not value.strip():
        raise ManifestError(f"{what}.{key} is required (text)")
    return value.strip()


def parse_manifest(text: str, path: Path) -> Manifest:
    """Validate the structure of a manifest. Enum values of the intake fields are checked by the
    AI system service when the system is registered."""
    try:
        raw = yaml.safe_load(text)
    except yaml.YAMLError as exc:
        raise ManifestError(f"not valid YAML ({type(exc).__name__})") from exc
    doc = _need_map(raw, "manifest")
    if doc.get("manifest_version") != 1:
        raise ManifestError("manifest_version must be 1")
    system = _need_map(doc.get("system"), "system")
    agent = _need_map(doc.get("agent"), "agent")
    fields: dict[str, Any] = {}
    for key in SYSTEM_REQUIRED:
        fields[key] = _need_text(system, key, "system")
    for key in SYSTEM_OPTIONAL:
        if system.get(key) is not None:
            fields[key] = system[key]
    for key in ("money_movement", "credit_decision"):
        if key in fields and not isinstance(fields[key], bool):
            raise ManifestError(f"system.{key} must be true or false")
    agent_id = _need_text(agent, "agent_id", "agent")
    try:
        check_agent_id(agent_id)
    except SupervisorError as exc:
        raise ManifestError(str(exc)) from exc
    plug_point = _need_text(agent, "plug_point", "agent")
    if plug_point not in PLUG_POINTS:
        raise ManifestError(f"agent.plug_point must be one of {', '.join(PLUG_POINTS)}")
    tools_raw = agent.get("tools")
    if not isinstance(tools_raw, list) or not tools_raw:
        raise ManifestError("agent.tools must be a list with at least one tool")
    tools: list[tuple[str, str]] = []
    for i, tool in enumerate(tools_raw):
        t = _need_map(tool, f"agent.tools[{i}]")
        name = _need_text(t, "name", f"agent.tools[{i}]")
        risk_class = _need_text(t, "risk_class", f"agent.tools[{i}]")
        if risk_class not in TOOL_RISK_CLASSES:
            raise ManifestError(
                f"agent.tools[{i}].risk_class must be one of {', '.join(TOOL_RISK_CLASSES)}"
            )
        tools.append((name, risk_class))
    return Manifest(
        system=fields,
        agent_id=agent_id,
        agent_name=str(agent.get("name") or fields["name"]).strip(),
        model_family=_need_text(agent, "model_family", "agent"),
        plug_point=plug_point,
        tools=tuple(tools),
        path=path,
    )


def load_manifest(path: Path) -> Manifest:
    if not path.is_file():
        raise ManifestError(f"{MANIFEST_NAME} not found")
    if path.stat().st_size > MAX_MANIFEST_BYTES:
        raise ManifestError("manifest is larger than 256 KB")
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        raise ManifestError(f"cannot read the manifest ({type(exc).__name__})") from exc
    return parse_manifest(text, path)


def candidate_folders(root: Path) -> list[Path]:
    """Sub-folders of the candidates dir (hidden ones left out), sorted by name."""
    if not root.is_dir():
        return []
    return sorted(p for p in root.iterdir() if p.is_dir() and not p.name.startswith("."))


def _ensure_agent(runtime: Any, m: Manifest) -> bool:
    """Add the registry row when absent. True when a row was added."""
    from supervisor.core.canonical import format_ts
    from supervisor.core.models import Agent

    a = runtime.adapters
    if a.state.get("agent", {"agent_id": m.agent_id}) is not None:
        return False
    now = a.clock.now()
    row = Agent(
        agent_id=m.agent_id,
        name=m.agent_name,
        owner_team=m.system["owner_team"],
        owner_user=m.system["owner_user"],
        risk_tier=m.risk_tier,  # type: ignore[arg-type]
        host_type="app",
        plug_point=m.plug_point,
        model_family=m.model_family,
        status="shadow",
        gate_state="SHADOW",
        created_at=now,
    ).row()
    row.pop("row_version", None)
    row.pop("updated_at", None)
    a.state.insert("agent", row)
    runtime.gateway.states.invalidate(m.agent_id)
    runtime.chain.record(
        "agent_registered",
        m.agent_id,
        {
            "agent_id": m.agent_id,
            "risk_tier": row["risk_tier"],
            "model_family": row["model_family"],
            "gate_state": "SHADOW",
            "ts": format_ts(now),
        },
    )
    return True


def seed_one(session: Any, m: Manifest, say: Echo, rep: SeedSystemsReport) -> None:
    from supervisor.governance.model import SystemsError
    from supervisor.governance.systems import system_id_for

    systems = session.console.systems
    classification = session.console.classification
    actor = m.system["owner_user"]
    sid = system_id_for(m.system["name"])
    existing = session.state.get("ai_system", {"system_id": sid})
    try:
        if existing is None:
            systems.register(m.system, actor)
            rep.created += 1
            say(f"[OK] system registered: {m.system['name']} -> {sid}")
        else:
            say(f"[OK] system already registered: {m.system['name']} -> {sid}")
        if _ensure_agent(session.runtime, m):
            say(f"[OK] agent registered: {m.agent_id} (risk tier {m.risk_tier}, shadow)")
        else:
            say(f"[OK] agent already registered: {m.agent_id}")
        systems.link(sid, "agent", m.agent_id, actor)
        say(f"[OK] agent {m.agent_id} linked to {sid}")
        if classification.get(sid)["draft"] is None and classification.get(sid)["applied"] is None:
            classification.draft(sid, actor)
            say(f"[OK] classification draft made for {sid} (a person applies it)")
        else:
            say(f"[OK] classification already present for {sid}")
    except SystemsError as exc:
        rep.skipped += 1
        say(f"[SKIP] {m.path.parent.name}: invalid manifest or refused by the registry: {exc}")
        return
    rep.systems[m.system["name"]] = sid


def seed_systems(
    settings: Settings,
    candidates_dir: Path | str | None = None,
    echo: Echo = default_echo,
    *,
    snapshot: bool = True,
) -> SeedSystemsReport:
    """Register the systems of every manifest found. Never raises for a bad manifest."""
    from supervisor.demo import reset

    rep = SeedSystemsReport()

    def say(line: str) -> None:
        rep.lines.append(line)
        echo(line)

    root = Path(os.path.abspath(Path(candidates_dir or DEFAULT_CANDIDATES_DIR).expanduser()))
    folders = candidate_folders(root)
    if not folders:
        say(f"[SKIP] no candidate folders under {root}")
        rep.skipped += 1
        return rep
    manifests: list[Manifest] = []
    for folder in folders:
        try:
            manifests.append(load_manifest(folder / MANIFEST_NAME))
        except ManifestError as exc:
            rep.skipped += 1
            say(f"[SKIP] {folder.name}: {exc}")
    if not manifests:
        return rep
    data_dir = Path(settings.data_dir)
    if data_dir.exists() and any(data_dir.iterdir()) and not is_demo_dir(data_dir):
        rep.fail(f"{data_dir} is not a demo data dir (run: demo seed). Nothing was written")
        echo(rep.lines[-1])
        return rep
    if not is_demo_dir(data_dir):
        mark_demo_dir(data_dir)  # empty or new: ours from now on (a later run needs the marker)
    session = build_session(settings)
    try:
        for m in manifests:
            seed_one(session, m, say, rep)
    finally:
        session.close()
    say(f"[OK] seed-systems: {len(rep.systems)} system(s) present, {rep.created} new")
    for name, sid in sorted(rep.systems.items()):
        say(f"     {sid}  {name}")
    if snapshot and rep.created and reset.has_snapshot(data_dir):
        reset.snapshot(settings, echo=lambda _line: None)
        say("[OK] reset snapshot refreshed (demo reset now keeps these systems)")
    return rep


__all__ = [
    "MANIFEST_NAME",
    "Manifest",
    "ManifestError",
    "SeedSystemsReport",
    "parse_manifest",
    "seed_systems",
]

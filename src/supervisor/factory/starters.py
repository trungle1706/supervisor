"""Starter agents of the agent factory (WP-F5): load the committed definitions into the catalogue.

``config/factory_agents/<agent_id>.yaml`` holds six starter agents (state ``draft``) and two
templates (supply chain, reputation; also ``draft``, marked TEMPLATE in the description).
``config/factory_agents/golden/<agent_id>/cases.json`` (gate cases) and ``calibration.json``
(synthetic human-style labels) hold their golden sets; the dev tool ``tools/factory_golden_gen.py``
writes them.

``seed`` creates the agents the catalogue does not have yet. An id that already has a row is
skipped, unless the committed starter has a NEWER version than every row of the id (for example
the starter is 0.2 and the catalogue holds only 0.1): then the new version is added beside the old
one as a draft and the old rows stay untouched. A second call changes nothing, and a team's own
version (any version equal to or newer than the starter) is never replaced. The golden set is
kept per agent, not per version: starter case ids are merged in (same id, new content), a team's
cases under other ids stay. Seeding writes drafts only; promotion happens through the gate and
the approvals.
Run by ``python -m supervisor.factory seed`` and, with ``FACTORY_SEED_STARTERS=1`` and
``AGENT_FACTORY=1``, once at startup.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

import yaml

from supervisor.config import REPO_ROOT
from supervisor.factory import golden, store

log = logging.getLogger("supervisor.factory.starters")
STARTERS_DIR = REPO_ROOT / "config" / "factory_agents"
STARTER_IDS = (
    "model-risk-assessor",
    "data-governance-assessor",
    "cyber-assessor",
    "legal-compliance-assessor",
    "third-party-assessor",
    "ethics-assessor",
)
TEMPLATE_IDS = ("supply-chain-assessor", "reputation-assessor")
ACTOR = "starter.seed"


def _vkey(version: str) -> tuple[int, ...]:
    return tuple(int(x) for x in str(version).split(".") if x.isdigit())


def _read(path: Path) -> Any:
    try:
        return yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as exc:
        raise store.FactoryError("invalid_definition", f"{path.name}: cannot read it") from exc


def load_definitions(directory: Path | None = None) -> list[dict[str, Any]]:
    """The eight definitions as plain data, starters first. A missing file is an error."""
    base = directory or STARTERS_DIR
    out = []
    for agent_id in (*STARTER_IDS, *TEMPLATE_IDS):
        doc = _read(base / f"{agent_id}.yaml")
        if not isinstance(doc, dict) or doc.get("id") != agent_id:
            raise store.FactoryError(
                "invalid_definition", f"{agent_id}.yaml: id must be {agent_id}"
            )
        out.append(doc)
    return out


def load_golden(agent_id: str, directory: Path | None = None) -> tuple[list[Any], list[Any]]:
    """``(cases, labels)`` of the committed golden set; empty lists when a file is missing."""
    base = (directory or STARTERS_DIR) / "golden" / agent_id
    out: list[list[Any]] = []
    for name in ("cases.json", "calibration.json"):
        try:
            rows = json.loads((base / name).read_text(encoding="utf-8"))
        except (OSError, ValueError):
            rows = []
        out.append(rows if isinstance(rows, list) else [])
    return out[0], out[1]


def seed(
    fstore: store.FactoryStore,
    data_dir: Path,
    actor: str = ACTOR,
    directory: Path | None = None,
) -> dict[str, list[str]]:
    """Create the missing starter agents and templates as drafts and copy their golden sets.
    Returns the ids ``created`` (new id), ``added`` (``<id>@<version>``: a newer starter version
    added beside older rows) and ``skipped`` (an id that has this version or a newer one)."""
    created: list[str] = []
    added: list[str] = []
    skipped: list[str] = []
    for raw in load_definitions(directory):
        agent_id = str(raw["id"])
        existing = fstore.versions(agent_id)
        starter_version = str((raw.get("lifecycle") or {}).get("version") or "")
        if existing and not _vkey(starter_version) > _vkey(existing[-1]["version"]):
            skipped.append(agent_id)
            continue
        model = store.validate_definition(raw, fstore.tools, fstore.groups)
        if model.lifecycle.state != "draft":
            raise store.FactoryError("invalid_definition", f"{agent_id}: a starter stays draft")
        doc = model.model_dump(mode="json")
        fstore.state.insert(
            store.AGENT_TABLE,
            {
                "id": agent_id,
                "version": doc["lifecycle"]["version"],
                "owner_group": doc["owner_group"],
                "dimension_id": doc["dimension_id"],
                "definition_json": doc,
                "state": "draft",
                "created_by": actor,
            },
        )
        fstore.record_event(
            agent_id,
            doc["lifecycle"]["version"],
            "created",
            actor,
            "from starter definition"
            if not existing
            else f"starter version added beside {existing[-1]['version']}",
        )
        cases, labels = load_golden(agent_id, directory)
        ids = [c["id"] for c in doc["checklist"]]
        if cases:
            ok, bad = golden.check_gate_cases(cases, ids)
            if bad:
                raise store.FactoryError("invalid_golden", f"{agent_id}: {bad[0]['reason']}")
            golden.store_gate_cases(data_dir, agent_id, ok)
            fstore.record_event(
                agent_id,
                doc["lifecycle"]["version"],
                "golden_uploaded",
                actor,
                f"{len(ok)} starter gate cases",
            )
        if labels:
            good, bad2 = golden.check_labels(labels, [c["case_id"] for c in cases], ids)
            if bad2:
                raise store.FactoryError("invalid_golden", f"{agent_id}: {bad2[0]['reason']}")
            golden.store_labels(data_dir, agent_id, good)
        if existing:
            added.append(f"{agent_id}@{doc['lifecycle']['version']}")
        else:
            created.append(agent_id)
    return {"created": created, "added": added, "skipped": skipped}


def seed_for_runtime(settings: Any, runtime: Any) -> dict[str, list[str]] | None:
    """The startup hook: seed when ``FACTORY_SEED_STARTERS`` and the factory are on. Never raises
    (the caller logs); returns ``None`` when it did nothing."""
    if not (getattr(settings, "factory_seed_starters", False) and store.enabled(settings)):
        return None
    from supervisor.console.context import build_context

    ctx = build_context(runtime)
    fstore = store.FactoryStore(ctx.state, ctx.tables, ctx.clock)
    result = seed(fstore, Path(settings.data_dir))
    if result["created"] or result["added"]:
        log.info("starter agents created: %s", ", ".join([*result["created"], *result["added"]]))
    return result

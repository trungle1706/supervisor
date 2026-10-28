"""Starter templates of the agent factory (WP-F2): ``config/factory_templates/<dimension>.yaml``.

One template per risk dimension (eight). A template is the body of an agent definition: the
starter checklist (from ``docs/phase12/research/regulation-structure.md`` section 2), the group
tools, the mandatory guardians and the harness defaults. Strict keys: an unknown or missing key
is a ``TemplateError`` that names the file and the field. ``build_definition`` turns a template
into a definition that ``agent_definition_v1`` validates; a template never bypasses the schema.
"""

from __future__ import annotations

import copy
from collections.abc import Mapping
from pathlib import Path
from typing import Any

import yaml

from supervisor.config import REPO_ROOT
from supervisor.core.errors import SupervisorError
from supervisor.factory import caps

TEMPLATES_DIR = REPO_ROOT / "config" / "factory_templates"
KEYS = (
    "template_id",
    "version",
    "label_en",
    "name",
    "description",
    "owner_group",
    "dimension_id",
    "policy_refs",
    "checklist",
    "evidence_rules",
    "tools",
    "instructions",
    "harness",
    "guardians",
    "eval_pack",
)


class TemplateError(SupervisorError):
    """A template file is wrong. The message names the file and the field."""


def load_template(dimension_id: str, directory: Path | None = None) -> dict[str, Any]:
    if dimension_id not in caps.DIMENSIONS:
        raise TemplateError(f"{dimension_id!r} is not a dimension ({', '.join(caps.DIMENSIONS)})")
    path = (directory or TEMPLATES_DIR) / f"{dimension_id}.yaml"
    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as exc:
        raise TemplateError(f"{path.name}: cannot read the file ({type(exc).__name__})") from exc
    if not isinstance(raw, Mapping):
        raise TemplateError(f"{path.name}: must be an object")
    unknown = sorted(str(k) for k in set(raw) - set(KEYS))
    if unknown:
        raise TemplateError(f"{path.name}: unknown key: {', '.join(unknown)}")
    missing = [k for k in KEYS if k not in raw]
    if missing:
        raise TemplateError(f"{path.name}: missing key: {', '.join(missing)}")
    if raw["template_id"] != dimension_id or raw["dimension_id"] != dimension_id:
        raise TemplateError(f"{path.name}: template_id and dimension_id must be {dimension_id}")
    if raw["version"] != 1:
        raise TemplateError(f"{path.name}: version must be 1")
    return copy.deepcopy(dict(raw))


def list_templates(directory: Path | None = None) -> list[dict[str, Any]]:
    """The eight templates, in the order of ``caps.DIMENSIONS``."""
    return [load_template(d, directory) for d in caps.DIMENSIONS]


def build_definition(
    template: Mapping[str, Any], *, agent_id: str, name: str | None = None, version: str = "0.1"
) -> dict[str, Any]:
    """A draft definition from a template. The result is plain data; the caller validates it."""
    skip = ("template_id", "version", "label_en")
    body = {k: copy.deepcopy(v) for k, v in template.items() if k not in skip}
    body["schema_version"] = caps.SCHEMA_VERSION
    body["id"] = agent_id
    if name:
        body["name"] = name[: caps.NAME_MAX]
    body["output_schema"] = {"type": caps.OUTPUT_SCHEMA}
    body["lifecycle"] = {"state": "draft", "version": version, "approvals": []}
    return body

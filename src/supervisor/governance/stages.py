"""Lifecycle stage policy (WP-G1): which stage moves of a system need an approval.

``config/tasks.yaml`` marks them in an optional block::

    stages:
      deployment: {approval: true}
      operation: {approval: true}

Without the block the default is the same: the move into ``deployment`` and ``operation`` needs
an approved ``stage_approval`` row. ILLUSTRATIVE until the bank sets its own, like the rest of
the file. Pure Python apart from reading the YAML file.
"""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from typing import Any

import yaml

from supervisor.governance.model import LIFECYCLE_STAGES, SystemsError
from supervisor.tasks.model import DEFAULT_CONFIG

DEFAULT_APPROVAL: dict[str, bool] = {s: s in ("deployment", "operation") for s in LIFECYCLE_STAGES}


def parse_policy(doc: Any, name: str = "tasks.yaml") -> dict[str, bool]:
    """Stage -> approval needed, from the parsed YAML document. A missing block is the default."""
    out = dict(DEFAULT_APPROVAL)
    block = doc.get("stages") if isinstance(doc, Mapping) else None
    if block is None:
        return out
    if not isinstance(block, Mapping):
        raise SystemsError(f"{name}: stages must be a mapping")
    for stage, spec in block.items():
        if stage not in LIFECYCLE_STAGES:
            raise SystemsError(f"{name}: stages has an unknown stage {stage!r}")
        flag = spec.get("approval", False) if isinstance(spec, Mapping) else None
        if not isinstance(flag, bool):
            raise SystemsError(f"{name}: stages.{stage}.approval must be true or false")
        out[str(stage)] = flag
    return out


def load_policy(path: Path | str | None = None) -> dict[str, bool]:
    p = Path(path) if path else DEFAULT_CONFIG
    if not p.is_file():
        return dict(DEFAULT_APPROVAL)
    try:
        doc = yaml.safe_load(p.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError):
        raise SystemsError(f"{p.name}: cannot read the stage policy") from None
    return parse_policy(doc, p.name)


def needs_approval(policy: Mapping[str, bool], to_stage: str) -> bool:
    return bool(policy.get(to_stage, False))

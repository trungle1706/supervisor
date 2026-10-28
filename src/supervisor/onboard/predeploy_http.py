"""WP-O3b: which candidate gets the HTTP target in the pre-deploy assessment.

The target is used only when ``PREDEPLOY_HTTP_TARGET`` is on, ``PREDEPLOY_HTTP_ALLOWED_HOSTS``
names at least one host, and the candidate has an ``http_target`` block. The block comes from

1. the stored tree: ``supervisor.manifest.yaml`` (root or one folder down), key ``http_target``
   at the top level or under ``agent``; or
2. an inventory node of kind ``system`` (its id or name is the node id) whose ``attrs`` hold a
   ``url`` or ``app_url``: the block is then that URL with the defaults.

A block that the rules refuse (host not on the list, http, a bad field name) is not silently
dropped: ``resolve`` raises ``TargetError`` and the report shows a ``fail`` item.

The allow list is the only thing that decides which host gets the Supervisor token. A candidate's
own tree can name a URL, but a host that is not on the list is refused.
"""

from __future__ import annotations

import json
import logging
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from supervisor.assurance.targets import (
    HttpTargetConfig,
    TargetError,
    http_target_config,
    split_allowed_hosts,
)

log = logging.getLogger(__name__)

MANIFEST_NAME = "supervisor.manifest.yaml"
MAX_MANIFEST_BYTES = 256 * 1024


def enabled(settings: Any) -> bool:
    """True when the flag is on and the allow list names a host."""
    return bool(
        getattr(settings, "predeploy_http_target", False)
        and split_allowed_hosts(getattr(settings, "predeploy_http_allowed_hosts", ""))
    )


def _tree_block(tree: Path) -> Mapping[str, Any] | None:
    import yaml

    if not tree.is_dir():
        return None
    try:
        folders = [tree, *sorted(p for p in tree.iterdir() if p.is_dir())]
    except OSError:
        return None
    for folder in folders:
        path = folder / MANIFEST_NAME
        try:
            if not path.is_file() or path.stat().st_size > MAX_MANIFEST_BYTES:
                continue
            doc = yaml.safe_load(path.read_text(encoding="utf-8"))
        except Exception:  # noqa: BLE001, S112 - an unreadable manifest only means "no block"
            continue
        if not isinstance(doc, Mapping):
            continue
        agent = doc.get("agent")
        for block in (
            doc.get("http_target"),
            agent.get("http_target") if isinstance(agent, Mapping) else None,
        ):
            if block is not None:
                return block if isinstance(block, Mapping) else {"url": ""}
    return None


def agent_ids(tree: Path, node_id: str) -> list[str]:
    """Agent ids the candidate may have in the registry: the node id, the ``agent.agent_id`` of
    ``supervisor.manifest.yaml`` and the ``id`` of ``manifest.yaml`` (root or one folder down)."""
    import yaml

    out = [node_id]
    if not tree.is_dir():
        return out
    try:
        folders = [tree, *sorted(p for p in tree.iterdir() if p.is_dir())]
    except OSError:
        return out
    for folder in folders:
        for name, pick in ((MANIFEST_NAME, "agent.agent_id"), ("manifest.yaml", "id")):
            path = folder / name
            try:
                if not path.is_file() or path.stat().st_size > MAX_MANIFEST_BYTES:
                    continue
                doc = yaml.safe_load(path.read_text(encoding="utf-8"))
            except Exception:  # noqa: BLE001, S112 - unreadable: skip
                continue
            if not isinstance(doc, Mapping):
                continue
            if pick == "id":
                val = doc.get("id")
            else:
                agent = doc.get("agent")
                val = agent.get("agent_id") if isinstance(agent, Mapping) else None
            if isinstance(val, str) and val.strip() and val.strip() not in out:
                out.append(val.strip())
    return out


def _inventory_block(state: Any, node_id: str) -> Mapping[str, Any] | None:
    try:
        rows = state.query("inventory_node", {"kind": "system"})
    except Exception:  # noqa: BLE001 - no inventory table or store: no block
        return None
    for r in rows:
        if r.get("node_id") != node_id and r.get("name") != node_id:
            continue
        attrs = r.get("attrs")
        if isinstance(attrs, str):
            try:
                attrs = json.loads(attrs)
            except ValueError:
                attrs = {}
        if isinstance(attrs, Mapping):
            url = attrs.get("url") or attrs.get("app_url")
            if url:
                return {"url": str(url)}
    return None


def resolve(settings: Any, state: Any, node_id: str, tree: Path) -> HttpTargetConfig | None:
    """The validated config for this candidate, or ``None`` when the HTTP target is not in use.
    Raises ``TargetError`` when a block exists and the rules refuse it."""
    if not enabled(settings):
        return None
    block = _tree_block(tree)
    if block is None:
        block = _inventory_block(state, node_id)
    if block is None:
        return None
    return http_target_config(
        block,
        allowed_hosts=split_allowed_hosts(settings.predeploy_http_allowed_hosts),
        max_timeout_s=int(settings.predeploy_http_timeout_s),
        max_turns=int(settings.predeploy_http_max_turns),
        max_budget_s=int(settings.predeploy_http_budget_s),
    )


__all__ = ["TargetError", "agent_ids", "enabled", "resolve"]

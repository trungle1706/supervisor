"""Library tools (WP-G6): scope ``library.read``, read only.

The shared catalogues every person sees in the console: the regulation knowledge base, the
starter risks and controls, the guardian (detector) catalogue and the assignment rules. Nothing
here depends on the scope of an AI system. The server never writes to the library.
"""

from __future__ import annotations

import functools
import logging
from pathlib import Path
from typing import Any

import yaml

from supervisor.core.errors import NotFoundError, SupervisorError
from supervisor.mcp_server.common import LIMIT_SPEC, limit_of, plain
from supervisor.mcp_server.registry import Registry, Tool

log = logging.getLogger("supervisor.mcp_server")
NOT_LEGAL_ADVICE = "Not legal advice. Bank counsel must confirm."


@functools.lru_cache(maxsize=4)
def _kb(internal_dir: str) -> Any:
    from supervisor.regkb import load_kb

    return load_kb(internal_dir=Path(internal_dir) if internal_dir else None)


def _knowledge_base(call: Any) -> Any:
    try:
        return _kb(str(call.ctx.settings.regkb_internal_dir or ""))
    except SupervisorError:
        raise
    except Exception as exc:  # noqa: BLE001 - a bad file is a message, not a 500
        log.error("regkb load failed: %s", type(exc).__name__)
        raise SupervisorError(
            f"the regulation knowledge base cannot be loaded: {type(exc).__name__}"
        ) from None


def regulations(call: Any, a: dict[str, Any], apply: bool) -> dict[str, Any]:
    kb = _knowledge_base(call)
    counts: dict[str, int] = {}
    for o in kb.obligations.values():
        counts[o.instrument_id] = counts.get(o.instrument_id, 0) + 1
    rows = [
        {
            "instrument_id": i.id,
            "jurisdiction": i.jurisdiction,
            "number": i.number,
            "title_en": i.title_en,
            "title_vi": i.title_vi,
            "status": i.status,
            "binding": i.binding,
            "obligations": counts.get(i.id, 0),
        }
        for i in kb.instruments
        if not a.get("jurisdiction") or i.jurisdiction == a["jurisdiction"]
    ]
    return {
        "version": kb.version,
        "disclaimer": NOT_LEGAL_ADVICE,
        "count": len(rows),
        "items": rows,
    }


def obligations(call: Any, a: dict[str, Any], apply: bool) -> dict[str, Any]:
    kb = _knowledge_base(call)
    words = [w for w in str(a.get("query") or "").lower().split() if w]
    out = []
    for o in kb.obligations.values():
        if a.get("instrument_id") and o.instrument_id != a["instrument_id"]:
            continue
        hay = " ".join(
            [o.id, o.article_ref, o.title_en, o.summary_en, o.summary_vi or "", *o.duties]
        ).lower()
        if all(w in hay for w in words):
            out.append(
                {
                    "obligation_id": o.id,
                    "instrument_id": o.instrument_id,
                    "article_ref": o.article_ref,
                    "summary_en": o.summary_en,
                    "summary_vi": o.summary_vi,
                    "duties": list(o.duties),
                    "status": o.status,
                    "binding": o.binding,
                    "verification": o.verification,
                }
            )
    limit = limit_of(a)
    return {
        "disclaimer": NOT_LEGAL_ADVICE,
        "count": len(out),
        "truncated": len(out) > limit,
        "items": out[:limit],
    }


def _starter(folder: Path, key: str, fields: tuple[str, ...]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    if not folder.is_dir():
        return rows
    for p in sorted(folder.glob("*.yaml")):
        try:
            doc = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
        except (OSError, yaml.YAMLError):
            log.warning("starter file %s cannot be read", p.name)
            continue
        for item in doc.get(key, []) if isinstance(doc, dict) else []:
            if isinstance(item, dict) and isinstance(item.get("id"), str):
                row = {"id": item["id"]}
                row.update({f: plain(item[f]) for f in fields if f in item})
                rows.append(row)
    return rows


def starter_risks(call: Any, a: dict[str, Any], apply: bool) -> dict[str, Any]:
    rows = _starter(
        Path(call.ctx.settings.risk_starter_dir),
        "risks",
        ("title", "category", "inherent", "treatment", "residual", "owner", "status", "links"),
    )
    return {"count": len(rows), "items": rows[: limit_of(a)]}


def starter_controls(call: Any, a: dict[str, Any], apply: bool) -> dict[str, Any]:
    rows = _starter(
        Path(call.ctx.settings.controls_starter_dir),
        "controls",
        ("title", "objective", "type", "implemented_by", "owner", "status", "agents", "covers"),
    )
    return {"count": len(rows), "items": rows[: limit_of(a)]}


def guardian_catalog(call: Any, a: dict[str, Any], apply: bool) -> dict[str, Any]:
    """The detector catalogue of the running gate; else the detectors named in the config."""
    gate = getattr(call.ctx.gateway, "detector_gate", None)
    if gate is not None:
        items = plain(gate.registry.catalogue())
        return {"enabled": True, "count": len(items), "items": items}
    items = []
    try:
        doc = yaml.safe_load(Path(call.ctx.settings.detectors_config).read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError):
        doc = None
    for slug, cfg in sorted(((doc or {}).get("detectors") or {}).items()):
        cfg = cfg if isinstance(cfg, dict) else {}
        items.append(
            {
                "slug": str(slug),
                "enabled": bool(cfg.get("enabled", False)),
                "fail_closed": bool(cfg.get("fail_closed", False)),
            }
        )
    return {"enabled": False, "count": len(items), "items": items}


def assignment_rules(call: Any, a: dict[str, Any], apply: bool) -> dict[str, Any]:
    path = Path(call.ctx.settings.assignment_rules_config)
    try:
        doc = yaml.safe_load(path.read_text(encoding="utf-8")) or []
    except (OSError, yaml.YAMLError):
        raise NotFoundError("the assignment rules file cannot be read") from None
    rows = [
        {k: plain(r[k]) for k in ("id", "title", "when", "assign") if k in r}
        for r in (doc if isinstance(doc, list) else [])
        if isinstance(r, dict)
    ]
    return {"count": len(rows), "items": rows[: limit_of(a)]}


def register(reg: Registry) -> None:
    def tool(name: str, text: str, fn: Any, props: dict[str, Any] | None = None) -> None:
        reg.register(
            Tool(name, text, "library.read", {"properties": props or {"limit": LIMIT_SPEC}}, fn)
        )

    tool(
        "regulations",
        "The instruments of the regulation knowledge base (Vietnam and international). Not legal "
        "advice.",
        regulations,
        {"jurisdiction": {"type": "string", "maxLength": 16}},
    )
    tool(
        "obligations",
        "Search obligations by words in the id, article, title, summary or duty. Not legal advice.",
        obligations,
        {
            "query": {"type": "string", "maxLength": 200},
            "instrument_id": {"type": "string", "maxLength": 128},
            "limit": LIMIT_SPEC,
        },
    )
    tool("starter_risks", "The starter risk catalogue (config/risks).", starter_risks)
    tool("starter_controls", "The starter control catalogue (config/controls).", starter_controls)
    tool("guardian_catalog", "The guardian (detector) catalogue.", guardian_catalog, {})
    tool(
        "assignment_rules", "The assignment rules (config/assignment_rules.yaml).", assignment_rules
    )

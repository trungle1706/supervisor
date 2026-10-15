"""Read model of the Compliance tab (WP14): matrices of the compliance advisor, read-only.

Data sources:
* the three demo agents: ``demo_product`` -> ``build_matrix`` (cached per process);
* products onboarded with ``ONBOARD_COMPLIANCE_ENABLED=1``: the JSON file
  ``<data_dir>/onboard/<agent>/compliance_matrix.json`` (read-only, no rebuild).

The RegKB is loaded once per process and internal rules directory. Advisory only. Not legal
advice. Bank counsel must confirm.
"""

from __future__ import annotations

import json
import re
from functools import cache
from pathlib import Path
from typing import Any

from supervisor.advisory.compliance import demo_product
from supervisor.advisory.compliance.demo import DEMO_AGENTS
from supervisor.advisory.compliance.i18n import tr
from supervisor.advisory.compliance.matrix import build_matrix
from supervisor.advisory.compliance.model import STATUSES, to_plain
from supervisor.console import readmodels
from supervisor.core.errors import SupervisorError
from supervisor.regkb import DISCLAIMER, KnowledgeBase, load_kb

AGENT_RE = re.compile(r"^[A-Za-z0-9_-][A-Za-z0-9_.-]{0,63}$")
OBLIGATION_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,127}$")
FILTER_RE = re.compile(r"^[A-Za-z0-9_.:-]{1,128}$")
MATRIX_FILE = "compliance_matrix.json"
MAX_JSON_BYTES = 20_000_000
STATUS_PILL = {
    "met": "ok",
    "partial": "warn",
    "gap": "bad",
    "bank_process": "teal",
    "not_applicable": "neutral",
}
D33_PILL = {"high_risk": "bad", "not_high_risk": "ok", "needs_answer": "warn"}


class ComplianceInputError(SupervisorError):
    """Bad Compliance request (HTTP 400): unknown agent or obligation, bad filter."""


@cache
def _kb(internal: str) -> KnowledgeBase:
    return load_kb(internal_dir=Path(internal) if internal else None)


def kb_for(settings: Any) -> KnowledgeBase:
    return _kb(str(getattr(settings, "regkb_internal_dir", "") or ""))


@cache
def _demo_matrix(internal: str, agent: str) -> dict[str, Any]:
    matrix = build_matrix(_kb(internal), demo_product(agent), chat=None)
    plain = to_plain(matrix)
    plain["source_kind"] = "demo"
    return plain


_json_cache: dict[tuple[str, int], dict[str, Any]] = {}


def _onboard_file(settings: Any, agent: str) -> Path:
    return readmodels.onboard_dir(settings, agent) / MATRIX_FILE


def _read_json(path: Path) -> dict[str, Any] | None:
    try:
        st = path.stat()
        if st.st_size > MAX_JSON_BYTES:
            return None
        key = (str(path), st.st_mtime_ns)
        if key not in _json_cache:
            data = json.loads(path.read_text(encoding="utf-8"))
            if not isinstance(data, dict) or not isinstance(data.get("rows"), list):
                return None
            data["source_kind"] = "onboard"
            _json_cache.clear()  # keep one generation only
            _json_cache[key] = data
        return _json_cache[key]
    except (OSError, ValueError):
        return None


def onboarded_agents(settings: Any) -> list[str]:
    root = readmodels.onboard_dir(settings, "x").parent
    try:
        names = sorted(p.name for p in root.iterdir() if p.is_dir())
    except OSError:
        return []
    return [n for n in names if AGENT_RE.match(n) and _onboard_file(settings, n).is_file()]


def agent_ids(settings: Any) -> list[str]:
    extra = [n for n in onboarded_agents(settings) if n not in DEMO_AGENTS]
    return [*DEMO_AGENTS, *extra]


def matrix_for(settings: Any, agent: str) -> dict[str, Any]:
    """Plain matrix dict of ``agent``; ``ComplianceInputError`` when there is none."""
    if not AGENT_RE.match(agent or ""):
        raise ComplianceInputError("invalid agent id")
    if agent in DEMO_AGENTS:
        return _demo_matrix(str(getattr(settings, "regkb_internal_dir", "") or ""), agent)
    if agent in onboarded_agents(settings):
        data = _read_json(_onboard_file(settings, agent))
        if data is not None:
            return data
    raise ComplianceInputError(f"no compliance matrix for agent {agent!r}")


def card(agent: str, m: dict[str, Any]) -> dict[str, Any]:
    s = m.get("summary", {})
    by = s.get("by_status", {})
    return {
        "agent": agent,
        "name": m.get("header", {}).get("product_name", agent),
        "source_kind": m.get("source_kind", ""),
        "by_status": {k: by.get(k, 0) for k in STATUSES},
        "applies_yes": s.get("by_applies", {}).get("yes", 0),
        "needs_answer": s.get("needs_answer", 0),
        "questions": s.get("questions", len(m.get("questions", []))),
        "threshold_gaps": s.get("threshold_gaps", 0),
        "d33": m.get("decision33", {}).get("classification", "needs_answer"),
        "as_of": m.get("header", {}).get("as_of", ""),
        "regkb_version": m.get("header", {}).get("regkb_version", ""),
    }


def cards(settings: Any) -> list[dict[str, Any]]:
    out = []
    for agent in agent_ids(settings):
        try:
            out.append(card(agent, matrix_for(settings, agent)))
        except ComplianceInputError:
            continue
    return out


def _clean(value: str, what: str) -> str:
    value = (value or "").strip()
    if value and not FILTER_RE.match(value):
        raise ComplianceInputError(f"invalid {what} filter")
    return value


def filter_rows(
    m: dict[str, Any], *, instrument: str = "", status: str = "", duty: str = "", applies: str = ""
) -> dict[str, Any]:
    """Validated filter over the rows; returns rows plus the option lists for the form."""
    instrument = _clean(instrument, "instrument")
    duty = _clean(duty, "duty")
    status = _clean(status, "status")
    applies = _clean(applies, "applies")
    if status and status not in STATUSES:
        raise ComplianceInputError("invalid status filter")
    if applies and applies not in ("yes", "no", "needs_answer"):
        raise ComplianceInputError("invalid applies filter")
    rows = m.get("rows", [])
    shown = [
        r
        for r in rows
        if (not instrument or r.get("instrument_id") == instrument)
        and (not status or r.get("status") == status)
        and (not applies or r.get("applies") == applies)
        and (not duty or duty in (r.get("duties") or []))
    ]
    return {
        "rows": shown,
        "total": len(rows),
        "instruments": sorted({r.get("instrument_id", "") for r in rows}),
        "duties": sorted({d for r in rows for d in (r.get("duties") or [])}),
        "instrument": instrument,
        "status": status,
        "duty": duty,
        "applies": applies,
    }


def obligation_detail(settings: Any, agent: str, obligation_id: str) -> dict[str, Any]:
    if not OBLIGATION_RE.match(obligation_id or ""):
        raise ComplianceInputError("invalid obligation id")
    m = matrix_for(settings, agent)
    ob = kb_for(settings).obligations.get(obligation_id)
    row = next((r for r in m.get("rows", []) if r.get("obligation_id") == obligation_id), None)
    if ob is None or row is None:
        raise ComplianceInputError(f"unknown obligation {obligation_id!r}")
    return {
        "matrix": m,
        "row": row,
        "ob": ob,
        "controls": [
            {"kind": c.kind, "id": c.id, "coverage": c.coverage, "note": c.note or ""}
            for c in ob.control_mapping
        ],
    }


def status_word(status: str, lang: str) -> str:
    try:
        return tr(f"status.{status}", lang)
    except KeyError:
        return status


def word(key: str, lang: str) -> str:
    try:
        return tr(key, lang)
    except KeyError:
        return key


__all__ = [
    "D33_PILL",
    "DISCLAIMER",
    "STATUSES",
    "STATUS_PILL",
    "ComplianceInputError",
    "agent_ids",
    "card",
    "cards",
    "filter_rows",
    "kb_for",
    "matrix_for",
    "obligation_detail",
    "onboarded_agents",
    "status_word",
    "word",
]

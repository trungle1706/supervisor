"""UX5 view helpers of group G4 (CONSOLE_UX5): catalogue tabs, integrations, users, tools.

Pure functions on the dicts the existing views already build; routes call them only when
``settings.console_ux5`` is on. They bound long lists (search, paging at 25, fold identical rows)
and never change a number."""

from __future__ import annotations

import re
from collections import Counter
from collections.abc import Mapping, Sequence
from typing import Any

from supervisor.console.ux5 import page_slice

ASSET_STATUSES = ("active", "unmanaged", "allowlisted")


def _qs(**kv: str) -> str:
    from urllib.parse import urlencode

    return urlencode({k: v for k, v in kv.items() if v})


def asset_view(d: Mapping[str, Any], query: Mapping[str, str]) -> dict[str, Any]:
    """Catalogue asset tab: de-duplicate, filter (q, status), page at 25.

    Duplicate nodes (same name, kind and status) become one row with ``n`` (how many nodes)."""
    q = (query.get("q") or "").strip().lower()[:80]
    status = query.get("status") if query.get("status") in ASSET_STATUSES else ""
    seen: dict[tuple[str, str, str], dict[str, Any]] = {}
    for r in d["rows"]:
        key = (r["name"], r["kind"], r["status"])
        if key in seen:
            seen[key]["n"] += 1
            if (r.get("last_seen") or "") > (seen[key].get("last_seen") or ""):
                seen[key]["last_seen"] = r.get("last_seen")
        else:
            seen[key] = {**r, "n": 1}
    rows = sorted(seen.values(), key=lambda r: (str(r["name"]).lower(), r["kind"]))
    total = len(rows)
    counts = Counter(r["status"] for r in rows)
    if q:
        rows = [r for r in rows if q in str(r["name"]).lower()]
    if status:
        rows = [r for r in rows if r["status"] == status]
    shown, page, pages = page_slice(rows, query.get("page"))
    base = _qs(tab=d["tab"], q=q, status=status)
    return {
        **d,
        "rows": shown,
        "ux": {
            "total": total,
            "matched": len(rows),
            "page": page,
            "pages": pages,
            "q": q,
            "status": status,
            "counts": dict(counts),
            "base": "/console/catalogues?" + base,
            "show_risk": any(r.get("own_risk") for r in d["rows"]),
            "kinds": sorted({r["kind"] for r in d["rows"]}),
            "dups": any(r["n"] > 1 for r in seen.values()),
        },
    }


def integration_agents(
    agents: Sequence[Mapping[str, Any]], query: Mapping[str, str]
) -> dict[str, Any]:
    """Integrations page: the agents table shows the exceptions (an agent with a key, or one that
    differs from the common case) and one fold line for the identical rows, paged at 25.

    ``view=all`` lists every agent."""

    def sig(a: Mapping[str, Any]) -> tuple[Any, ...]:
        return (a.get("gate_state"), bool(a.get("has_key")), a.get("mode"), a.get("consumers"))

    counts = Counter(sig(a) for a in agents)
    common = counts.most_common(1)[0][0] if counts else None
    view_all = query.get("view") == "all"
    pool = (
        list(agents) if view_all else [a for a in agents if sig(a) != common or counts[common] < 3]
    )
    if not view_all and common is not None and counts[common] >= 3:
        folded = counts[common]
    else:
        folded = 0
    rows, page, pages = page_slice(pool, query.get("page"))
    nokey = sum(1 for a in agents if not a.get("has_key"))
    return {
        "rows": rows,
        "page": page,
        "pages": pages,
        "total": len(agents),
        "folded": folded,
        "common": {
            "gate_state": common[0] if common else None,
            "has_key": common[1] if common else False,
            "mode": common[2] if common else None,
        },
        "view_all": view_all,
        "nokey": nokey,
    }


# Words in a permission description that name a work package, e.g. "(WP-UX3)" or "WP31".

_WP = re.compile(r"[,;]?\s*\bWP-?[A-Z]*\d+[A-Za-z]*\b")
_EMPTY = re.compile(r"\s*[\(\[]\s*[\)\]]")


def strip_wp(text: str) -> str:
    """Remove work-package ids from a permission description (business view)."""
    return _EMPTY.sub("", _WP.sub("", text or "")).strip(" ,;:-")

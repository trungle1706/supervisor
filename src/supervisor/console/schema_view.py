"""Schema self-check page helpers (WP-P3): the admin banner and a plain fallback page.

The page ``/console/admin/schema`` shows the result of ``supervisor.ops.schema_selfcheck`` and
the SQL plan a person runs. It is read only: the app never runs DDL. When the console context
cannot be built (a missing table is the usual cause), ``standalone_html`` answers instead, so
the plan stays reachable.
"""

from __future__ import annotations

from html import escape
from typing import Any

from supervisor.ops import schema_selfcheck


def current_runtime() -> Any:
    from supervisor.gateway import wiring as gate_wiring

    return getattr(gate_wiring, "_runtime", None)


def banner(me: Any) -> dict[str, int] | None:
    """Data for the banner on admin pages: only an admin sees it, only when tables or columns
    are missing. Never raises (a banner is a convenience)."""
    try:
        if "admin" not in getattr(me, "roles", ()):
            return None
        check = schema_selfcheck.get_state()
        if check is None or not check.problem:
            return None
        return {"tables": len(check.missing_tables), "cols": check.missing_column_count}
    except Exception:  # noqa: BLE001
        return None


def standalone_html(check: schema_selfcheck.SchemaCheck, reason: str) -> str:
    plan = "".join(f"{stmt};\n\n" for stmt in check.plan)
    rows = [
        f"<li>Status: <b>{escape(check.status)}</b></li>",
        f"<li>Checked at: {escape(check.checked_at or '-')}</li>",
        f"<li>Missing tables: {escape(', '.join(check.missing_tables) or 'none')}</li>",
        f"<li>Missing columns: {check.missing_column_count}</li>",
    ]
    if check.detail:
        rows.append(f"<li>Detail: {escape(check.detail)}</li>")
    return (
        '<!doctype html><html lang="en"><head><meta charset="utf-8">'
        "<title>Supervisor console - schema check</title>"
        '<link rel="stylesheet" href="/console/static/console.css"></head><body><main>'
        "<h1>Schema check</h1>"
        f"<p>The console shell did not start ({escape(reason)}). This plain page still shows "
        "the schema plan. The app never runs DDL: run the SQL below in the SQL editor, then "
        "restart the app.</p>"
        f"<ul>{''.join(rows)}</ul>"
        + (
            '<textarea id="sch-plan" class="mono" readonly rows="30" style="width:100%">'
            f"{escape(plan)}</textarea>"
            if plan
            else ""
        )
        + "</main></body></html>"
    )

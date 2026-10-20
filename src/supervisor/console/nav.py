"""Sidebar structure (WP-UX1): six groups, each item with its flag rule and its count badge.

Pure data and one function; the template (``_c_sidebar.html``) only loops over the result.
Hidden nav is not security: every route still checks its permission (``core/rbac.py``).
Items for pages that WP-UX3 has not built yet (``placeholder=True``) open a "coming in WP-UX3"
page and show only when ``CONSOLE_NAV_PLACEHOLDERS=1``."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

# Placeholder pages and the label key of each (the route /console/soon/<page> accepts only these).
PLACEHOLDERS: dict[str, str] = {
    "decisions": "nav_decisions",
    "traces": "nav_traces",
    "policies": "nav_policies",
    "credentials": "nav_credentials",
    "users": "nav_users",
    "audit": "nav_audit",
    "integrations": "nav_integrations",
}


@dataclass(frozen=True)
class Item:
    key: str  # the ``section`` a page sets to mark this item active
    label: str  # i18n key
    href: str
    count: str | None = None  # key in shell() for the badge
    hot: str | None = None  # key in shell() that turns the badge red when truthy
    flag: str | None = None  # "compliance" | "integration" | "assurance" | "tools" | "inventory"
    placeholder: bool = False
    page: str | None = None  # WP-UX3: key in PAGES; shows the real page when its flag is on


# --- WP-UX3 --- the seven pages and the Playground, each behind its own setting. With the flag
# on the sidebar item opens the real page; with it off the item opens the "coming" placeholder
# when CONSOLE_NAV_PLACEHOLDERS=1, else it is hidden.
PAGES: dict[str, str] = {
    "decisions": "console_decisions_enabled",
    "traces": "console_traces_enabled",
    "policies": "console_policies_enabled",
    "credentials": "console_credentials_enabled",
    "users": "console_users_enabled",
    "audit": "console_auditlog_enabled",
    "integrations": "console_integrations_enabled",
    "playground": "console_playground_enabled",
    "risks": "console_risks_enabled",  # WP29
    "transparency": "console_transparency_enabled",  # WP31
}


def _soon(page: str) -> Item:
    return Item(page, PLACEHOLDERS[page], f"/console/soon/{page}", placeholder=True, page=page)


# (group i18n key or None, items). Order is the reading order of the sidebar.
GROUPS: tuple[tuple[str | None, tuple[Item, ...]], ...] = (
    (None, (Item("overview", "nav_overview", "/console/"),)),
    (
        "nav_g_watch",
        (
            Item("agents", "agents", "/console/agents", count="agents_n"),
            _soon("decisions"),
            _soon("traces"),
            Item("alerts", "nav_alerts", "/console/alerts", count="alerts_n", hot="alerts_n"),
        ),
    ),
    (
        "nav_g_act",
        (
            Item("cases", "cases", "/console/cases", count="cases_n", hot="critical_n"),
            Item(
                "signoff",
                "signoff",
                "/console/signoff",
                count="signoff_n",
                hot="signoff_n",
            ),
            Item("inbox", "inbox", "/console/inbox", count="unread", hot="unread"),
        ),
    ),
    (
        "nav_g_prove",
        (
            Item("evidence", "nav_evidence", "/console/evidence"),
            Item("assurance", "nav_assurance", "/console/assurance", flag="assurance"),
            Item("compliance", "nav_compliance", "/console/compliance", flag="compliance"),
            Item("risks", "nav_risks", "/console/risks", page="risks"),  # WP29
            Item(
                "transparency", "nav_transparency", "/console/transparency", page="transparency"
            ),  # WP31
        ),
    ),
    (
        "nav_g_onboard",
        (
            Item("onboard", "nav_onboard", "/console/onboard"),
            Item(
                "inventory",
                "nav_inventory",
                "/console/inventory",
                count="inventory_n",
                hot="inventory_n",
                flag="inventory",
            ),
            Item("integration", "nav_integration", "/console/integration", flag="integration"),
            Item("playground", "nav_playground", "/console/playground", page="playground"),
        ),
    ),
    (
        "nav_g_analytics",
        (
            # WP-UX2: Tools and Metrics are tabs of one Analytics page (old URLs redirect)
            Item("analytics", "nav_analytics", "/console/analytics"),
        ),
    ),
    (
        "nav_g_settings",
        (
            _soon("policies"),
            _soon("credentials"),
            _soon("users"),
            _soon("audit"),
            _soon("integrations"),
            Item("health", "nav_health", "/console/health"),
        ),
    ),
)


# Short codes shown when the sidebar is collapsed (wide screens). Two letters, unique, the same in
# EN and VI (like unit symbols); the full label stays in the link's title tooltip and is the
# link's accessible name. One-letter initials were ambiguous (Agents, Alerts, Assurance...).
CODES: dict[str, str] = {
    "overview": "OV",
    "agents": "AG",
    "decisions": "GD",
    "traces": "TR",
    "alerts": "AL",
    "cases": "CS",
    "signoff": "SO",
    "inbox": "IB",
    "evidence": "EV",
    "assurance": "AS",
    "compliance": "CO",
    "onboard": "ON",
    "inventory": "IV",
    "integration": "IG",
    "analytics": "AN",  # WP-UX2: Tools and Metrics are tabs of Analytics
    "policies": "PO",
    "credentials": "CR",
    "users": "US",
    "audit": "AU",
    "integrations": "IS",
    "playground": "PG",  # WP-UX3
    "risks": "RK",  # WP29
    "transparency": "TP",  # WP31
    "health": "HL",
}


def _page_on(item: Item, sh: dict[str, Any]) -> bool:
    return bool(item.page and (sh.get("pages") or {}).get(item.page))


def _visible(item: Item, sh: dict[str, Any], compliance: bool, integration: bool) -> bool:
    if item.page and _page_on(item, sh):
        return True
    if item.placeholder:
        return bool(sh.get("placeholders"))
    if item.page:
        return False
    return {
        None: True,
        "compliance": compliance,
        "integration": integration,
        "assurance": bool(sh.get("assurance")),
        "tools": bool(sh.get("tools")),
        "inventory": sh.get("inventory_n") is not None,
    }[item.flag]


def _real_path(item: Item) -> str:
    return f"/console/{item.page}"


def href(path: str, lang: str) -> str:
    """``path`` with ``lang=`` added before any #fragment."""
    base, hash_, frag = path.partition("#")
    joined = f"{base}{'&' if '?' in base else '?'}lang={lang}"
    return f"{joined}#{frag}" if hash_ else joined


def groups(
    sh: dict[str, Any], *, compliance: bool, integration: bool, lang: str = "en"
) -> list[dict[str, Any]]:
    """Visible groups with resolved counts: ``[{label, items: [{item, code, href, n, hot}]}]``. A
    group with no visible item is dropped."""
    out: list[dict[str, Any]] = []
    for label, items in GROUPS:
        rows = []
        for it in items:
            if not _visible(it, sh, compliance, integration):
                continue
            n = sh.get(it.count) if it.count else None
            path = _real_path(it) if _page_on(it, sh) else it.href
            rows.append(
                {
                    "item": it,
                    "code": CODES[it.key],
                    "href": href(path, lang),
                    "n": n,
                    "hot": bool(it.hot and sh.get(it.hot)),
                }
            )
        if rows:
            out.append({"label": label, "items": rows})
    return out

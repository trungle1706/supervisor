"""Merged sidebar (CONSOLE_NAV_V3, WP-UX4a): one bar with My overview, five Governance items,
six Supervisor items and a settings gear, plus the tab strip each section shows over its pages.

Pure data and a few functions; the templates (``_c_sidebar_v3.html``, ``_c_section_tabs.html``)
only loop over the result. An item or tab shows only when its page flag is on and the role holds
its permission; hidden nav is not security, every route still checks its own permission.

A tab is a link to a page that already exists (Decisions, Cases, Risks ...) or to one of the
small pages this package routes (Models, Detectors ...). The old URLs keep working."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from supervisor.console.nav import href
from supervisor.core import rbac


@dataclass(frozen=True)
class Tab:
    key: str
    label: str  # i18n key
    path: str  # final destination (an existing page, or /console/<section>?tab=<key>)
    need: str | None = None  # None | ux3:<page> | assurance | compliance | integration | inventory
    perm: str | None = None


@dataclass(frozen=True)
class Sec:
    key: str
    label: str  # i18n key
    route: str
    tabs: tuple[Tab, ...]


SECTIONS_V3: dict[str, Sec] = {
    "systems": Sec(
        "systems",
        "nv3_systems",
        "/console/systems",
        (
            Tab("onboard", "nav_onboard", "/console/onboard", perm="onboard.view"),
            Tab("integration", "nav_integration", "/console/integration", "integration"),
            Tab("transparency", "nav_transparency", "/console/transparency", "ux3:transparency"),
            Tab("tasks", "nav_tasks", "/console/tasks", "ux3:tasks"),
        ),
    ),
    "catalogues": Sec(
        "catalogues",
        "nv3_catalogues",
        "/console/catalogues",
        (
            Tab("agents", "agents", "/console/agents"),
            Tab("models", "nv3_t_models", "/console/catalogues?tab=models", "inventory"),
            Tab("tools", "nv3_t_tools", "/console/catalogues?tab=tools", "inventory"),
            Tab("datasets", "nv3_t_datasets", "/console/catalogues?tab=datasets", "inventory"),
            Tab("mcp", "nv3_t_mcp", "/console/catalogues?tab=mcp", "inventory"),
            Tab("unmanaged", "nv3_t_unmanaged", "/console/inventory", "inventory"),
        ),
    ),
    "risks_controls": Sec(
        "risks_controls",
        "nv3_risks_controls",
        "/console/risks-controls",
        (
            Tab("risks", "nav_risks", "/console/risks", "ux3:risks"),
            Tab("controls", "nav_controls", "/console/controls", "ux3:controls"),
            Tab("policies", "nv3_t_policies", "/console/compliance", "compliance"),
        ),
    ),
    "activity": Sec(
        "activity",
        "nv3_activity",
        "/console/activity",
        (
            Tab("decisions", "nav_decisions", "/console/decisions", "ux3:decisions"),
            Tab("traces", "nav_traces", "/console/traces", "ux3:traces"),
        ),
    ),
    "guardians": Sec(
        "guardians",
        "nv3_guardians",
        "/console/guardians",
        (
            Tab("library", "nv3_t_library", "/console/catalog", "ux3:catalog"),
            Tab("rules", "nv3_t_rules", "/console/policies", "ux3:policies"),
            Tab("detectors", "nv3_t_detectors", "/console/guardians?tab=detectors"),
            Tab("judges", "nv3_t_judges", "/console/guardians?tab=judges"),
            Tab("monitors", "nv3_t_monitors", "/console/guardians?tab=monitors"),
            Tab("packs", "nv3_t_packs", "/console/assurance", "assurance"),
        ),
    ),
    "cases_alerts": Sec(
        "cases_alerts",
        "nv3_cases_alerts",
        "/console/cases",
        (
            Tab("cases", "cases", "/console/cases"),
            Tab("alerts", "nav_alerts", "/console/alerts", perm="metrics.view"),
            Tab("approvals", "nv3_t_approvals", "/console/signoff"),
        ),
    ),
    "analytics": Sec(
        "analytics",
        "nav_analytics",
        "/console/analytics",
        (
            Tab("analytics", "nav_analytics", "/console/analytics", perm="metrics.view"),
            Tab("evidence", "nv3_t_evidence", "/console/evidence"),
        ),
    ),
}

# The page keys the routes pass as ``section=``, and where each sits: (bar item, section, tab).
PAGE_HOME: dict[str, tuple[str, str | None, str | None]] = {
    "overview": ("home", None, None),
    "inbox": ("home", None, None),
    "gov_overview": ("gov_overview", None, None),
    "sup_overview": ("sup_overview", None, None),
    "workflows": ("workflows", None, None),
    "playground": ("playground", None, None),
    "onboard": ("systems", "systems", "onboard"),
    "integration": ("systems", "systems", "integration"),
    "transparency": ("systems", "systems", "transparency"),
    "tasks": ("systems", "systems", "tasks"),
    "agents": ("catalogues", "catalogues", "agents"),
    "inventory": ("catalogues", "catalogues", "unmanaged"),
    "cat_models": ("catalogues", "catalogues", "models"),
    "cat_tools": ("catalogues", "catalogues", "tools"),
    "cat_datasets": ("catalogues", "catalogues", "datasets"),
    "cat_mcp": ("catalogues", "catalogues", "mcp"),
    "risks": ("risks_controls", "risks_controls", "risks"),
    "controls": ("risks_controls", "risks_controls", "controls"),
    "compliance": ("risks_controls", "risks_controls", "policies"),
    "decisions": ("activity", "activity", "decisions"),
    "traces": ("activity", "activity", "traces"),
    "catalog": ("guardians", "guardians", "library"),
    "policies": ("guardians", "guardians", "rules"),
    "g_detectors": ("guardians", "guardians", "detectors"),
    "g_judges": ("guardians", "guardians", "judges"),
    "g_monitors": ("guardians", "guardians", "monitors"),
    "assurance": ("guardians", "guardians", "packs"),
    "cases": ("cases_alerts", "cases_alerts", "cases"),
    "alerts": ("cases_alerts", "cases_alerts", "alerts"),
    "signoff": ("cases_alerts", "cases_alerts", "approvals"),
    "analytics": ("analytics", "analytics", "analytics"),
    "evidence": ("analytics", "analytics", "evidence"),
}


@dataclass(frozen=True)
class BarItem:
    key: str
    label: str  # i18n key
    icon: str  # key in _icons.html
    path: str
    sec: str | None = None  # a section: visible when one of its tabs is
    need: str | None = None  # a page of its own: its flag
    perm: str | None = None


# (group key, group title key, kicker key, items). Order is the reading order of the bar.
BAR: tuple[tuple[str, str, str, tuple[BarItem, ...]], ...] = (
    (
        "gov",
        "nv3_gov",
        "nv3_gov_k",
        (
            BarItem("gov_overview", "nv3_overview", "overview", "/console/governance"),
            BarItem("systems", "nv3_systems", "systems", "/console/systems", "systems"),
            BarItem("catalogues", "nv3_catalogues", "layers", "/console/catalogues", "catalogues"),
            BarItem(
                "risks_controls",
                "nv3_risks_controls",
                "shield",
                "/console/risks-controls",
                "risks_controls",
            ),
            BarItem("workflows", "nv3_workflows", "branch", "/console/workflows"),
        ),
    ),
    (
        "sup",
        "nv3_sup",
        "nv3_sup_k",
        (
            BarItem("sup_overview", "nv3_overview", "overview", "/console/supervisor"),
            BarItem("activity", "nv3_activity", "pulse", "/console/activity", "activity"),
            BarItem("guardians", "nv3_guardians", "sliders", "/console/guardians", "guardians"),
            BarItem("cases_alerts", "nv3_cases_alerts", "bell", "/console/cases", "cases_alerts"),
            BarItem("analytics", "nav_analytics", "bars", "/console/analytics", "analytics"),
            BarItem(
                "playground",
                "nav_playground",
                "flask",
                "/console/playground",
                need="ux3:playground",
                perm="playground.run",
            ),
        ),
    ),
)


@dataclass(frozen=True)
class GearItem:
    key: str
    label: str  # i18n key
    path: str
    need: str | None
    perm: str
    status: str


# The six items of today's Settings group, behind the gear. With CONSOLE_NAV_PLACEHOLDERS=1 a
# page that is still off opens its "coming" page, as in the old sidebar.
GEAR: tuple[GearItem, ...] = (
    GearItem(
        "integrations", "nav_integrations", "/console/integrations", "ux3:integrations",
        "integrations.view", "collectors",
    ),
    GearItem(
        "credentials", "nav_credentials", "/console/credentials", "ux3:credentials",
        "credentials.view", "ingress",
    ),
    GearItem("users", "nav_users", "/console/users", "ux3:users", "users.view", "auth"),
    GearItem("audit", "nav_audit", "/console/audit", "ux3:audit", "audit.view", "audit"),
    GearItem("health", "nav_health", "/console/health", None, "health.view", "mode"),
    GearItem(
        "policies", "nv3_policies_code", "/console/policies", "ux3:policies", "policies.view",
        "policy",
    ),
)  # fmt: skip

_PLACEHOLDER_PAGES = {"integrations", "credentials", "users", "audit", "policies"}


def _on(need: str | None, sh: dict[str, Any], compliance: bool, integration: bool) -> bool:
    if need is None:
        return True
    if need.startswith("ux3:"):
        return bool((sh.get("pages") or {}).get(need[4:]))
    return {
        "assurance": bool(sh.get("assurance")),
        "compliance": compliance,
        "integration": integration,
        "inventory": sh.get("inventory_n") is not None,
    }[need]


def _may(roles: frozenset[str], perm: str | None) -> bool:
    return perm is None or rbac.allowed(roles, perm)


def visible_tabs(
    sec: str, sh: dict[str, Any], roles: Any, *, compliance: bool, integration: bool
) -> list[Tab]:
    roles = frozenset(roles)
    return [
        t
        for t in SECTIONS_V3[sec].tabs
        if _on(t.need, sh, compliance, integration) and _may(roles, t.perm)
    ]


def bar(
    sh: dict[str, Any],
    roles: Any,
    *,
    compliance: bool,
    integration: bool,
    lang: str,
    active: str,
    actions_n: int | None,
    systems_on: bool = False,
) -> dict[str, Any]:
    """The bar for one request: ``{home, groups: [{key, label, kicker, items}]}``. An item is
    ``{key, label, icon, href, n, hot, active}``."""
    roles = frozenset(roles)

    def row(it: BarItem | None, n: int | None, hot: bool) -> dict[str, Any]:
        key, label, icon, path = (
            (it.key, it.label, it.icon, it.path) if it else ("home", "nv3_my", "home", "/console/")
        )
        return {
            "key": key,
            "label": label,
            "icon": icon,
            "href": href(path, lang),
            "n": n,
            "hot": hot,
            "active": key == active,
        }

    groups = []
    for gkey, glabel, gkicker, items in BAR:
        rows = []
        for it in items:
            if it.key == "systems" and not systems_on:
                # the Systems page is WP-G0's: shown only with console_systems_enabled
                continue
            if it.sec is not None:
                if not visible_tabs(
                    it.sec, sh, roles, compliance=compliance, integration=integration
                ):
                    continue
            elif not (_on(it.need, sh, compliance, integration) and _may(roles, it.perm)):
                continue
            n, hot = None, False
            if it.key == "cases_alerts":  # badge: open cases plus open alerts
                n = int(sh.get("cases_n") or 0) + int(sh.get("alerts_n") or 0)
                hot = bool(sh.get("critical_n") or sh.get("alerts_n"))
            rows.append(row(it, n, hot))
        if rows:
            groups.append({"key": gkey, "label": glabel, "kicker": gkicker, "items": rows})
    return {"home": row(None, actions_n, bool(actions_n)), "groups": groups}


def gear(
    sh: dict[str, Any], roles: Any, settings: Any, *, auth_kind: str, lang: str
) -> list[dict[str, Any]]:
    """The settings drawer: link plus a one-line status read from settings (no queries)."""
    roles = frozenset(roles)
    out = []
    for g in GEAR:
        if not _may(roles, g.perm):
            continue
        if _on(g.need, sh, False, False):
            link = g.path
        elif sh.get("placeholders") and g.key in _PLACEHOLDER_PAGES:
            link = f"/console/soon/{g.key}"
        else:
            continue
        out.append(
            {
                "key": g.key,
                "label": g.label,
                "href": href(link, lang),
                "status": _status(g.status, settings, auth_kind),
            }
        )
    return out


def _status(kind: str, s: Any, auth_kind: str) -> tuple[str, dict[str, str]]:
    """(i18n key, format values) of the one-line status."""

    def sw(base: str, value: Any) -> tuple[str, dict[str, str]]:
        return (f"{base}_{'on' if value else 'off'}", {})

    if kind == "collectors":
        return sw("nv3_st_collectors", getattr(s, "collectors_enabled", False))
    if kind == "ingress":
        return sw("nv3_st_ingress", getattr(s, "ingress_auth_enabled", False))
    if kind == "audit":
        return sw("nv3_st_audit", getattr(s, "console_audit_enabled", True))
    if kind == "auth":
        return ("nv3_st_auth", {"kind": auth_kind})
    if kind == "mode":
        return ("nv3_st_mode", {"mode": str(getattr(s, "supervisor_mode", ""))})
    return ("nv3_st_policy", {})


def tab_strip(
    page: str, sh: dict[str, Any], roles: Any, *, compliance: bool, integration: bool, lang: str
) -> dict[str, Any] | None:
    """The tab strip of the section that holds ``page`` (a ``section=`` value), or None."""
    home = PAGE_HOME.get(page)
    if home is None or home[1] is None:
        return None
    sec = SECTIONS_V3[home[1]]
    tabs = visible_tabs(sec.key, sh, roles, compliance=compliance, integration=integration)
    if not tabs:
        return None
    return {
        "label": sec.label,
        "tabs": [{"key": t.key, "label": t.label, "href": href(t.path, lang)} for t in tabs],
        "active": home[2],
    }


def active_item(page: str) -> str:
    home = PAGE_HOME.get(page)
    return home[0] if home else ""

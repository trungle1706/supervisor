"""Catalog page (CONSOLE_CATALOG_ENABLED): every guardian capability, grouped by category, with
whether it is on in this instance and the setting that turns it on.

Read-only. The page never switches a capability: settings come from the environment and the
detector file, so a card shows the setting to change, not a button that pretends to change it.
Status is read from the live settings and ``config/detectors.yaml`` on every request."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from supervisor.console import nav

# Category order is the reading order of the page. (key, i18n label key)
CATEGORIES: tuple[tuple[str, str], ...] = (
    ("gate", "catg_gate"),
    ("detect", "catg_detect"),
    ("judge", "catg_judge"),
    ("monitor", "catg_monitor"),
    ("prove", "catg_prove"),
    ("connect", "catg_connect"),
)

# What a capability may do, by the product rules: only deterministic rules block or pause,
# judges advise, monitors open cases, evidence proves. (pill class, i18n key)
KINDS: dict[str, tuple[str, str]] = {
    "blocks": ("bad", "catk_blocks"),
    "transforms": ("teal", "catk_transforms"),
    "advises": ("gold", "catk_advises"),
    "watches": ("neutral", "catk_watches"),
    "proves": ("ok", "catk_proves"),
}


@dataclass(frozen=True)
class Entry:
    key: str  # i18n: cat_<key> (name) and cat_<key>_d (description)
    cat: str
    kind: str
    icon: str  # two letters on the card tile
    env: str = ""  # what turns it on; empty = always on
    doc: str = ""  # repo-relative doc path, shown as text
    page: str | None = None  # console page key (nav.PAGES or a built-in section)
    on: Callable[[Any, dict[str, bool]], bool] | None = None  # None = always on


def _flag(name: str) -> Callable[[Any, dict[str, bool]], bool]:
    return lambda s, _d: bool(getattr(s, name, False))


def _detector(slug: str) -> Callable[[Any, dict[str, bool]], bool]:
    return lambda s, d: bool(getattr(s, "detectors_enabled", False)) and d.get(slug, False)


ENTRIES: tuple[Entry, ...] = (
    # --- gateway: deterministic, the only things that block or pause
    Entry("policy_rules", "gate", "blocks", "PR", doc="docs/policy.md", page="policies"),
    Entry("pause_switch", "gate", "blocks", "PS", doc="docs/policy.md", page="agents"),
    Entry(
        "session_monitor", "gate", "blocks", "SM", "SESSION_MONITOR_ENABLED=1",
        "docs/session-monitor.md", on=_flag("session_monitor_enabled"),
    ),
    Entry(
        "ingress_auth", "gate", "blocks", "IA", "INGRESS_AUTH_ENABLED=1",
        "docs/ingress-auth.md", "credentials", on=_flag("ingress_auth_enabled"),
    ),
    Entry(
        "mcp_gateway", "gate", "blocks", "MC", "MCP_HTTP_ENABLED=1",
        "docs/mcp-gateway.md", on=_flag("mcp_http_enabled"),
    ),
    # --- detectors (WP37): run inside the gate call
    Entry(
        "dlp_vn", "detect", "transforms", "DL", "DETECTORS_ENABLED=1 + dlp_vn.enabled",
        "docs/detectors.md", "decisions", on=_detector("dlp_vn"),
    ),
    Entry(
        "injection_regex", "detect", "watches", "IR",
        "DETECTORS_ENABLED=1 + injection_regex.enabled", "docs/detectors.md", "decisions",
        on=_detector("injection_regex"),
    ),
    Entry(
        "injection_classifier", "detect", "blocks", "IC",
        "DETECTORS_ENABLED=1 + injection_classifier.enabled", "docs/injection-classifier.md",
        "decisions", on=_detector("injection_classifier"),
    ),
    # WP-D1: document and URL intake. It reports (and, with the bank's fail_closed setting, fails
    # closed on money, credit and pii_export tools when a document cannot be read).
    Entry(
        "document_intake", "detect", "watches", "DI",
        "DOCUMENT_INTAKE_ENABLED=1 + DETECTORS_ENABLED=1", "docs/detectors.md", "decisions",
        on=lambda s, d: bool(getattr(s, "detectors_enabled", False))
        and bool(getattr(s, "document_intake_enabled", False))
        and d.get("document_intake", False),
    ),
    Entry(
        "inline_redaction", "detect", "transforms", "RD", "INLINE_REDACTION_ENABLED=1",
        "docs/masking.md", on=_flag("inline_redaction_enabled"),
    ),
    # --- AI judges: advise only
    Entry(
        "judge_tiers", "judge", "advises", "JT", "JUDGE_ENABLED=1", "docs/judge-mrm.md",
        "cases", on=_flag("judge_enabled"),
    ),
    Entry(
        "judge_advisory", "judge", "advises", "JA",
        "DETECTORS_ENABLED=1 + judge_advisory.enabled", "docs/detectors.md", "decisions",
        on=_detector("judge_advisory"),
    ),
    # WP-D4: toxicity and topic scope by the judge; advises only
    Entry(
        "judge_moderation", "judge", "advises", "JM",
        "DETECTORS_ENABLED=1 + judge_moderation.enabled", "docs/detectors.md", "decisions",
        on=_detector("judge_moderation"),
    ),
    Entry(
        "redteam", "judge", "advises", "RT", "REDTEAM_NIGHTLY_ENABLED=1",
        "docs/redteam-multiturn.md", "assurance", on=_flag("redteam_nightly_enabled"),
    ),
    # --- monitors: open cases and alerts
    Entry(
        "drift", "monitor", "watches", "DR", "DRIFT_ENABLED=1", "docs/monitors.md",
        "cases", on=_flag("drift_enabled"),
    ),
    Entry(
        "fairness", "monitor", "watches", "FA", "FAIRNESS_ENABLED=1", "docs/monitors.md",
        "cases", on=_flag("fairness_enabled"),
    ),
    Entry(
        "quality", "monitor", "advises", "QU", "QUALITY_ENABLED=1", "docs/monitors.md",
        "cases", on=_flag("quality_enabled"),
    ),
    Entry(
        "multiagent", "monitor", "watches", "MA", "MULTIAGENT_ENABLED=1", "docs/monitors.md",
        "cases", on=_flag("multiagent_enabled"),
    ),
    Entry(
        "tool_analytics", "monitor", "watches", "TA", "TOOL_ANALYTICS_ENABLED=1",
        "docs/tool-analytics.md", "analytics", on=_flag("tool_analytics_enabled"),
    ),
    Entry(
        "alerts", "monitor", "watches", "AL", "ALERTS_ENABLED=1", "docs/alerts.md", "alerts",
        on=_flag("alerts_enabled"),
    ),
    # --- evidence and assurance
    Entry("evidence_chain", "prove", "proves", "EC", doc="docs/recorder.md", page="evidence"),
    Entry("case_files", "prove", "proves", "CF", doc="docs/console.md", page="cases"),
    Entry(
        "assurance", "prove", "proves", "AP", "CONSOLE_ASSURANCE_ENABLED=1",
        "docs/assurance.md", "assurance", on=_flag("console_assurance_enabled"),
    ),
    Entry(
        "transparency", "prove", "proves", "TP", "TRANSPARENCY_ENABLED=1",
        "docs/transparency-report.md", "transparency", on=_flag("transparency_enabled"),
    ),
    # --- connectors
    Entry(
        "collectors", "connect", "watches", "CL", "COLLECTORS_ENABLED=1", "docs/collectors.md",
        "integrations", on=_flag("collectors_enabled"),
    ),
    Entry(
        "siem", "connect", "watches", "SI", "SIEM_ENABLED=1", "docs/siem.md",
        on=_flag("siem_enabled"),
    ),
    # --- WP-D3: guard model (ML jailbreak and indirect-injection scoring); advises, may only pause
    Entry(
        "guard_model", "detect", "advises", "GM",
        "DETECTORS_ENABLED=1 + guard_model.enabled", "docs/guard-model-decision.md", "decisions",
        on=_detector("guard_model"),
    ),
)  # fmt: skip

# Pages that are always there (not behind a WP-UX3 flag), by nav key.
_BUILTIN = {"agents", "cases", "evidence", "alerts", "analytics"}
_FLAGGED_BUILTIN = {"assurance": "console_assurance_enabled"}


def _detectors_on(settings: Any) -> dict[str, bool]:
    """``slug -> enabled`` from the detector file; empty when it cannot be read (the cards then
    show off, and the gate itself reports the bad file at start-up)."""
    from supervisor.detectors.config import load_config

    try:
        conf = load_config(settings.detectors_config)
    except Exception:  # noqa: BLE001 - a bad file is the gate's error, not this page's
        return {}
    return {slug: bool(e.enabled) for slug, e in conf.detectors.items()}


def _page_href(page: str | None, settings: Any, pages: dict[str, bool], lang: str) -> str | None:
    if page is None:
        return None
    if page in _BUILTIN:
        ok = True
    elif page in _FLAGGED_BUILTIN:
        ok = bool(getattr(settings, _FLAGGED_BUILTIN[page], False))
    else:
        ok = bool(pages.get(page))
    return nav.href(f"/console/{page}", lang) if ok else None


def page(
    ctx: Any, tab: str, lang: str = "en", me: Any = None, system: str | None = None
) -> dict[str, Any]:
    """``tab`` is ``catalog`` (every capability) or ``active`` (only those on)."""
    from supervisor.console import readmodels

    s = ctx.settings
    det = _detectors_on(s)
    pages = readmodels.ux3_pages(s)
    cards = []
    for e in ENTRIES:
        on = True if e.on is None else e.on(s, det)
        cards.append(
            {
                "e": e,
                "on": on,
                "kind": KINDS[e.kind],
                "href": _page_href(e.page, s, pages, lang),
                "mock": e.cat == "judge" and on and _judge_is_mock(s),
            }
        )
    n_on = sum(1 for c in cards if c["on"])
    shown = [c for c in cards if c["on"]] if tab == "active" else cards
    cats = []
    for key, label in CATEGORIES:
        rows = [c for c in shown if c["e"].cat == key]
        if rows:
            cats.append({"key": key, "label": label, "cards": rows})
    gb = None
    if me is not None:  # WP-S1: per-system switches; None unless GUARDIAN_BINDINGS_ENABLED
        from supervisor.console import guardians_view

        gb = guardians_view.catalog_panel(ctx, me, system)
    return {
        "tab": tab,
        "cats": cats,
        "n_all": len(cards),
        "n_on": n_on,
        "gb": gb,
    }


def _judge_is_mock(settings: Any) -> bool:
    """No JUDGE_T1_MODEL (or LLM_MOCK=1): the judges run the mock judge, labelled mock."""
    return bool(getattr(settings, "llm_mock", False)) or not getattr(settings, "judge_t1_model", "")


# --- UX5 (CONSOLE_UX5): one filterable list; effect chip, On/Off, docs and flags for admins only
_EFFECT = {
    "blocks": "cat_eff_blocks",
    "transforms": "cat_eff_masks",
    "advises": "cat_eff_advises",
    "watches": "cat_eff_reports",
    "proves": "cat_eff_proves",
}
_EFFECT_CLASS = {
    "blocks": "bad",
    "transforms": "info",
    "advises": "warn",
    "watches": "na",
    "proves": "ok",
}
# Guardians tabs (Detectors / Judges / Monitors) are filters of this one list.
TAB_TO_CAT = {"detectors": "detect", "judges": "judge", "monitors": "monitor"}


def ux5_page(
    ctx: Any,
    cat: str = "",
    state: str = "",
    lang: str = "en",
    me: Any = None,
    system: str | None = None,
) -> dict[str, Any]:
    """The catalog as one list: ``groups`` (filtered), counts for the filter strip, and the
    per-system switches. ``cat`` is a category key or empty; ``state`` is ``on``, ``off`` or empty."""
    from supervisor.detectors.config import load_config

    base = page(ctx, "catalog", lang, me, system)
    try:
        conf = load_config(ctx.settings.detectors_config)
        det = {slug: (bool(e.fail_closed), e.mrm_status) for slug, e in conf.detectors.items()}
    except Exception:  # noqa: BLE001 - a bad detector file is the gate's error
        det = {}
    if cat not in {k for k, _ in CATEGORIES}:
        cat = ""
    if state not in ("on", "off"):
        state = ""
    counts = {k: 0 for k, _ in CATEGORIES}
    groups = []
    for g in base["cats"]:
        counts[g["key"]] = len(g["cards"])
        if cat and g["key"] != cat:
            continue
        rows = []
        for c in g["cards"]:
            if (state == "on" and not c["on"]) or (state == "off" and c["on"]):
                continue
            e = c["e"]
            required, mrm = det.get(e.key, (False, ""))
            if e.key == "injection_classifier":
                eff_key, eff_cls = "cat_eff_pauses", "bad"
            else:
                eff_key, eff_cls = _EFFECT[e.kind], _EFFECT_CLASS[e.kind]
            rows.append(
                {**c, "eff_key": eff_key, "eff_cls": eff_cls, "required": required, "mrm": mrm}
            )
        if rows:
            groups.append({"key": g["key"], "label": g["label"], "rows": rows})
    admin = "admin" in getattr(me, "roles", ())
    tech: list[tuple[str, str]] = []
    if admin:
        for g in base["cats"]:
            for c in g["cards"]:
                e = c["e"]
                if e.env or e.doc:
                    tech.append((e.key, " · ".join(x for x in (e.env, e.doc) if x)))
    return {
        "groups": groups,
        "cat": cat,
        "state": state,
        "counts": counts,
        "n_all": base["n_all"],
        "n_on": base["n_on"],
        "gb": base["gb"],
        "tech": tech,
        "admin": admin,
    }

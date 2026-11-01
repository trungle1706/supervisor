"""One place that turns a raw id, key, flag name or kind into a human label (UI-330, UI-331).

A page never prints ``shw_ag_0036``, ``AR-D33-HIGH``, ``genie_space`` or ``RISK_REGISTER_ENABLED``
as the only text. It calls ``label_for(kind, ident)`` (a ``<span title="raw id">Name</span>``) or
``label_text(kind, ident)`` (plain text for a ``title=`` attribute or a sentence). The raw id is
kept in the ``title`` tooltip, so an admin can still copy it.

Kinds and where the name comes from:

* ``agent``    the ``name`` column of the agent registry (else the id)
* ``system``   the ``name`` column of the AI system register (else the id)
* ``rule``     an assignment rule id (``AR-D33-HIGH``): the i18n key ``lbl_rule_<id>``
* ``task``     a task template id (``DEP-D33``): the i18n key ``lbl_task_<id>``; the stored title
               is the fallback (it is free text and is kept as it is)
* ``guardian`` a detector or guardian feature key (``dlp_vn``): ``cat_<key>`` or a spaced word
* ``kind``     an inventory or catalogue kind (``genie_space``): ``lbl_kind_<kind>``
* ``flag``     a settings flag (``RISK_REGISTER_ENABLED``): ``lbl_flag_<flag>``
* any other kind (``gf_type``, ``gf_stage``, ``gf_act``, ``gf_group`` ...): ``lbl_<kind>_<id>``,
  else a spaced word

Pure helpers plus one small class built once per request by ``routes.render``. No I/O except the
two lazy name reads, which run only when a page asks for a name.
"""

from __future__ import annotations

import re
from collections.abc import Callable, Mapping
from typing import Any

from markupsafe import Markup, escape

KINDS = ("agent", "system", "rule", "task", "guardian", "kind", "flag")
_DEMO_PREFIX = re.compile(r"^\s*\[demo:showcase\]\s*")


def humanize(raw: str) -> str:
    """``genie_space`` -> ``Genie space``; ``REGKB_INTERNAL`` -> ``Regkb internal``. Last resort."""
    text = re.sub(r"[_\-.]+", " ", str(raw or "")).strip()
    return (text[:1].upper() + text[1:].lower()) if text else ""


def key_for(kind: str, ident: str) -> str:
    """The i18n key of a label: ``lbl_<kind>_<id>`` with every non-word char turned into ``_``."""
    return f"lbl_{kind}_{re.sub(r'[^A-Za-z0-9]+', '_', str(ident))}"


def strip_demo(text: Any) -> tuple[str, bool]:
    """(text without the ``[demo:showcase]`` seed tag, whether the tag was there). The stored
    value is never changed; only the view of it."""
    s = "" if text is None else str(text)
    m = _DEMO_PREFIX.match(s)
    return (s[m.end() :], True) if m else (s, False)


def agent_names(ctx: Any) -> dict[str, str]:
    """``{agent_id: name}`` from the agent registry (rows without a name are left out)."""
    return {str(a["agent_id"]): str(a["name"]) for a in ctx.state.query("agent") if a.get("name")}


def agent_opts(ctx: Any, ids: Any) -> list[tuple[str, str]]:
    """Filter options ``(id, label)``: the agent name first, sorted by name (UI-330)."""
    names = agent_names(ctx)
    return sorted(
        ((str(a), names.get(str(a), str(a))) for a in ids), key=lambda o: (o[1].lower(), o[0])
    )


def system_names(ctx: Any) -> dict[str, str]:
    """``{system_id: name}`` from the AI system register."""
    return {
        str(r["system_id"]): str(r["name"]) for r in ctx.state.query("ai_system") if r.get("name")
    }


class Labeler:
    """Names for ids, built once per request. ``agents`` and ``systems`` are callables that read
    ``{id: name}`` the first time a page needs a name (a page without ids pays nothing)."""

    def __init__(
        self,
        t: Callable[..., str],
        *,
        agents: Callable[[], Mapping[str, str]] | None = None,
        systems: Callable[[], Mapping[str, str]] | None = None,
        is_admin: bool = False,
    ) -> None:
        self.t = t
        self.is_admin = is_admin
        self._load = {"agent": agents, "system": systems}
        self._names: dict[str, Mapping[str, str]] = {}

    # ---------------------------------------------------------------- names
    def _name(self, kind: str, ident: str) -> str | None:
        if kind not in self._names:
            loader = self._load.get(kind)
            try:
                self._names[kind] = loader() if loader else {}
            except Exception:  # noqa: BLE001 - a label never breaks a page
                self._names[kind] = {}
        return self._names[kind].get(ident) or None

    def _keyed(self, kind: str, ident: str) -> str | None:
        key = key_for(kind, ident)
        text = self.t(key)
        return None if text == key else text

    def text(self, kind: str, ident: Any, fallback: Any = None) -> str:
        """The human label as plain text. Unknown ids fall back to ``fallback`` and then to a
        spaced word (kinds) or the id itself (agents, systems, rules, tasks)."""
        raw = "" if ident is None else str(ident)
        if not raw or raw == "-":
            return "-"
        found: str | None = None
        if kind in ("agent", "system"):
            found = self._name(kind, raw)
        elif kind == "guardian":
            found = self._keyed("guardian", raw)
            if found is None:
                cat = self.t(f"cat_{raw}")
                found = None if cat == f"cat_{raw}" else cat
        else:  # rule, task, kind, flag and every other kind: the i18n key lbl_<kind>_<id>
            found = self._keyed(kind, raw)
        if found:
            return found
        if fallback not in (None, ""):
            return str(fallback)
        if kind in ("agent", "system", "rule", "task"):
            return raw  # an id that has no name stays as it is
        return humanize(raw)

    def html(self, kind: str, ident: Any, fallback: Any = None) -> Markup:
        """``<span title="raw id">Label</span>``; just the escaped id when no label exists."""
        raw = "" if ident is None else str(ident)
        label = self.text(kind, ident, fallback)
        if not raw or label == raw or raw == "-":
            return escape(label)
        return Markup('<span class="lbl" title="{}">{}</span>').format(raw, label)

    # ---------------------------------------------------------------- flags and demo tag
    def flag_title(self, flag: str) -> Markup:
        """`` title="FLAG_NAME"`` for an admin, nothing for anyone else. A flag name is a
        developer word; a person who cannot change settings never sees it."""
        return Markup(' title="{}"').format(flag) if self.is_admin and flag else Markup("")

    def demo(self, text: Any) -> Markup:
        """Text with the ``[demo:showcase]`` seed tag turned into a small "Demo data" chip."""
        body, tagged = strip_demo(text)
        chip = (
            Markup('<span class="pill neutral" title="[demo:showcase]">{}</span> ').format(
                self.t("lbl_demo_data")
            )
            if tagged
            else Markup("")
        )
        return chip + escape(body)

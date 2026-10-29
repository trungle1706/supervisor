"""UX5 text overrides (CONSOLE_UX5). One line per module: add a new ``i18n_ux5_<page>.py`` that
exports ``UX5: dict[str, tuple[str, str]]`` (key -> (en, vi)) and list it in ``MODULES``.
An override never invents a key (a test checks that every key exists in the base table)."""

from __future__ import annotations

import importlib

MODULES: tuple[str, ...] = (
    "supervisor.console.i18n_ux5_base",
    "supervisor.console.i18n_ux5_g1",
    # add one line per page package, e.g. "supervisor.console.i18n_ux5_duties",
)

# Keys whose override text may be empty (the text is removed under UX5). Prefer a template
# conditional on ``ux5`` instead; list a key here only when that is not possible.
REMOVED: frozenset[str] = frozenset()

_cache: dict[str, tuple[str, str]] | None = None


def load() -> dict[str, tuple[str, str]]:
    """Merge every module's UX5 table (later modules win). Cached after the first call."""
    global _cache
    if _cache is None:
        merged: dict[str, tuple[str, str]] = {}
        for name in MODULES:
            merged.update(importlib.import_module(name).UX5)
        _cache = merged
    return _cache

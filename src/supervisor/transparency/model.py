"""Transparency report (WP31, ADR D31): constants, errors, input checks.

One report per agent, built from facts the system already holds. The data model is plain JSON:
integers, ids, hashes and masked text only (no floats, no raw PII). Three audiences (variants)
see different fields through explicit allow-lists (``allowlist.py``).
"""

from __future__ import annotations

import re
from typing import Any

from supervisor.core.errors import SupervisorError

SCHEMA_VERSION = 1  # the JSON data model; a change of shape raises it
GENERATOR = f"supervisor.transparency/{SCHEMA_VERSION}"
RECORD_TYPE = "transparency_report"
DIFF_RECORD_TYPE = "transparency_diff"

VARIANTS: tuple[str, ...] = ("regulator", "customer", "internal")
LANGS: tuple[str, ...] = ("vi", "en")
FORMATS: tuple[str, ...] = ("json", "html", "pdf")

# Section ids in the order of the report. ``controls`` is the hook for WP30 (control catalogue and
# task list): until that package registers a collector the section says "not built".
SECTIONS: tuple[str, ...] = (
    "identity",
    "classification",
    "inventory",
    "compliance",
    "cards",
    "assurance",
    "judge_mrm",
    "masking",
    "monitors",
    "risks",
    "controls",
    "evidence",
    "cases",
    "backlog",
    "not_shown",
)

MAX_ROWS = 40  # rows kept in any list; the rest is counted in ``more``
MAX_TEXT = 160  # characters kept of any free text
MAX_BACKLOG_ROWS = 12

# Reason codes for a section that is not available (fixed words; the renderer translates them).
REASONS: tuple[str, ...] = (
    "flag_off",  # the feature that holds the data is switched off
    "no_data",  # the source answered, with nothing for this agent
    "not_in_inventory",
    "no_matrix",
    "source_error",  # the source failed; the report says so rather than guessing
    "not_built",  # the work package that supplies it is not in this build
    "not_for_variant",
)

_ID = re.compile(r"^[A-Za-z0-9_.:-]{1,64}$")


class TransparencyError(SupervisorError):
    """Bad input or an operation the report refuses (HTTP 400 at a route)."""


class TransparencyOff(TransparencyError):
    """TRANSPARENCY_ENABLED is off (HTTP 400)."""


class UnknownAgent(TransparencyError):
    """The agent is not in the registry (HTTP 404 at a route)."""


def ensure_on(settings: Any) -> None:
    """TransparencyOff (HTTP 400) unless TRANSPARENCY_ENABLED is on."""
    if not settings.transparency_enabled:
        raise TransparencyOff(
            "Transparency reports are off (TRANSPARENCY_ENABLED=1 turns them on); "
            "python -m supervisor.transparency build <agent> works with the flag on"
        )


def check_agent(value: Any) -> str:
    if not isinstance(value, str) or not _ID.match(value):
        raise TransparencyError("agent id must be 1 to 64 characters from A-Z a-z 0-9 _ . : -")
    return value


def check_variant(value: Any) -> str:
    if value not in VARIANTS:
        raise TransparencyError(f"variant must be one of {', '.join(VARIANTS)}")
    return str(value)


def check_lang(value: Any) -> str:
    if value not in LANGS:
        raise TransparencyError(f"language must be one of {', '.join(LANGS)}")
    return str(value)


def check_format(value: Any) -> str:
    if value not in FORMATS:
        raise TransparencyError(f"format must be one of {', '.join(FORMATS)}")
    return str(value)


def assert_plain(value: Any, where: str = "report") -> None:
    """The data model holds JSON types only and no float (nothing signed may hold a float)."""
    if isinstance(value, float):
        raise TransparencyError(f"{where}: a float is not allowed in a report")
    if isinstance(value, dict):
        for k, v in value.items():
            if not isinstance(k, str):
                raise TransparencyError(f"{where}: keys must be text")
            assert_plain(v, f"{where}.{k}")
    elif isinstance(value, list | tuple):
        for i, v in enumerate(value):
            assert_plain(v, f"{where}[{i}]")
    elif value is not None and not isinstance(value, str | int | bool):
        raise TransparencyError(f"{where}: unsupported type {type(value).__name__}")

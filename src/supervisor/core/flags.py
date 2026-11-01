"""Flag helpers shared by services (audit D1)."""

from __future__ import annotations

from typing import Any


def truthy(value: Any) -> bool:
    """A state-table flag value as a bool.

    Delta returns booleans as text, so a string is compared by its text (``1`` or ``true``,
    any letter case, blanks ignored); every other type uses ``bool``.
    """
    if isinstance(value, str):
        return value.strip().lower() in ("1", "true")
    return bool(value)

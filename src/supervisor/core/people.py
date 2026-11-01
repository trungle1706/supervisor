"""Person and owner comparisons (audit D4)."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import Any

from supervisor.core.flags import truthy


def same_person(a: str | None, b: str | None) -> bool:
    """Two user ids name the same person (ids and e-mails are compared without letter case).
    An empty or missing id never matches."""
    return bool(a) and bool(b) and str(a).strip().casefold() == str(b).strip().casefold()


def is_system_owner(
    system: Mapping[str, Any] | None,
    team: Iterable[Mapping[str, Any]],
    user: str,
    *,
    exact: bool = False,
) -> bool:
    """The user owns the system: ``owner_user`` of the system row, or an active team member
    whose ``team_role`` is ``system_owner``.

    ``exact`` compares ids as they are (letter case counts). The classification path does this
    today; it is kept as a switch until the owner decides on case-insensitive ids.
    """

    def match(a: Any) -> bool:
        return (str(a or "") == user) if exact else same_person(str(a or ""), user)

    if system is not None and match(system.get("owner_user")):
        return True
    return any(
        match(m.get("user_id"))
        and m.get("team_role") == "system_owner"
        and truthy(m.get("active", True))
        for m in team
    )

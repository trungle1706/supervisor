"""Version hashes, built from plain dicts sorted by id: file order and YAML style do not matter."""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any

from supervisor.core.canonical import sha256_hex
from supervisor.regkb.model import Instrument, Obligation, to_plain


def instrument_hash(instrument: Instrument, obligations: Iterable[Obligation]) -> str:
    """Hash of one instrument header plus all its obligations."""
    return sha256_hex(
        {
            "instrument": to_plain(instrument),
            "obligations": sorted((to_plain(o) for o in obligations), key=lambda d: str(d["id"])),
        }
    )


def version_hash(instruments: Iterable[Instrument], obligations: Iterable[Obligation]) -> str:
    """Hash of the whole knowledge base."""
    return hash_plain([to_plain(i) for i in instruments], [to_plain(o) for o in obligations])


def hash_plain(instruments: list[dict[str, Any]], obligations: list[dict[str, Any]]) -> str:
    return sha256_hex(
        {
            "instruments": sorted(instruments, key=lambda d: str(d["id"])),
            "obligations": sorted(obligations, key=lambda d: str(d["id"])),
        }
    )

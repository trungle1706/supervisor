"""The ``regkb_draft`` table (WP-L1): drafts of the law agent and the decision of a person.

A draft is never an obligation. A person with ``regkb.confirm`` sets ``confirmed`` or
``dropped``; nothing else changes a draft after it is written. ``confirmed_by`` and
``confirmed_at`` record who decided (a drop records the person too).

Not legal advice. Bank counsel must confirm.
"""

from __future__ import annotations

import re
import secrets
from collections.abc import Mapping, Sequence
from typing import Any

from supervisor.core.errors import ConcurrencyError, SupervisorError
from supervisor.core.ports import Clock, StateStore

TABLE = "regkb_draft"
STATUSES = ("draft", "confirmed", "dropped")
SOURCES = ("model", "rule")
MAX_QUOTE = 2000
DRAFT_ID_RE = re.compile(r"^rkd_[0-9a-f]{20}$")


class DraftError(SupervisorError):
    """A draft cannot be written or decided (shown to the user as HTTP 400)."""


def new_draft_id() -> str:
    return "rkd_" + secrets.token_hex(10)


def quote_key(text: str) -> str:
    """Key for 'the same draft again': whitespace-folded quote."""
    return re.sub(r"\s+", " ", text).strip()


class DraftStore:
    """Reads and writes ``regkb_draft`` through the StateStore port."""

    def __init__(self, state: StateStore, clock: Clock) -> None:
        self.state = state
        self.clock = clock

    def add(self, rows: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
        out = []
        for row in rows:
            data = dict(row)
            data.setdefault("draft_id", new_draft_id())
            data.setdefault("status", "draft")
            data.setdefault("created_at", self.clock.now())
            if data["status"] != "draft":
                raise DraftError("a new draft must have status draft")
            if data.get("source") not in SOURCES:
                raise DraftError("source must be model or rule")
            if len(str(data.get("text_vi", ""))) > MAX_QUOTE:
                raise DraftError(f"the quote is longer than {MAX_QUOTE} characters")
            out.append(dict(self.state.insert(TABLE, data)))
        return out

    def get(self, draft_id: str) -> dict[str, Any] | None:
        row = self.state.get(TABLE, {"draft_id": draft_id})
        return dict(row) if row is not None else None

    def list(self, instrument_id: str, status: str | None = None) -> list[dict[str, Any]]:
        where: dict[str, Any] = {"instrument_id": instrument_id}
        if status is not None:
            where["status"] = status
        rows = self.state.query(TABLE, where, order_by=("created_at", "draft_id"))
        return [dict(r) for r in rows]

    def existing_keys(self, instrument_id: str) -> dict[tuple[str, str, str], str]:
        """(article, duty_id, quote key) -> status of every row of this instrument."""
        return {
            (r["article"], r["duty_id"], quote_key(r["text_vi"])): r["status"]
            for r in self.list(instrument_id)
        }

    def decide(
        self,
        draft_id: str,
        status: str,
        by: str,
        *,
        expected_version: int | None = None,
    ) -> dict[str, Any]:
        """draft -> confirmed | dropped. Another status, or a draft already decided, is an error."""
        if status not in ("confirmed", "dropped"):
            raise DraftError("a draft can only be confirmed or dropped")
        if not by:
            raise DraftError("the person who decides must be named")
        row = self.get(draft_id)
        if row is None:
            raise DraftError("this draft does not exist")
        if row["status"] != "draft":
            raise DraftError(f"this draft was already {row['status']}; reload the page")
        version = int(row["row_version"]) if expected_version is None else expected_version
        try:
            updated = self.state.update(
                TABLE,
                {"draft_id": draft_id},
                {"status": status, "confirmed_by": by, "confirmed_at": self.clock.now()},
                version,
            )
        except ConcurrencyError:
            raise DraftError("the draft was changed in another window; reload the page") from None
        return dict(updated)

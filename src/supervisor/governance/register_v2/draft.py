"""The ``registration_draft`` rows of the register workflow v2 (WP-N3).

Kind state, no evidence: a draft is working state and the chain gets nothing from it (the chain
sees the system, the agent and the classification when the submit writes them). A draft belongs
to one person; another person gets the same answer as for a draft that does not exist."""

from __future__ import annotations

import json
import secrets
from typing import Any

from supervisor.core.canonical import format_ts
from supervisor.core.errors import ConcurrencyError
from supervisor.governance.register_v2 import model as rm

MAX_DRAFTS_OPEN = 50
MAX_DATA_BYTES = 64_000


def _view(row: dict[str, Any]) -> dict[str, Any]:
    data = rm.json_of(row.get("data"), {})
    base = rm.empty_data()
    base.update(
        {
            k: v
            for k, v in (data if isinstance(data, dict) else {}).items()
            if k in (*base, "check", "result", "duties_answers", *rm.V3_DATA_KEYS)
        }
    )
    out = {k: row[k] for k in ("draft_id", "owner_user", "status", "source_kind", "source_ref")}
    out["step"] = int(row["step"])
    out["data"] = base
    out["row_version"] = int(row.get("row_version", 1))
    out["created_at"] = _ts(row.get("created_at"))
    out["updated_at"] = _ts(row.get("updated_at"))
    return out


def _ts(value: Any) -> str:
    return (
        format_ts(value) if value is not None and not isinstance(value, str) else str(value or "")
    )


class DraftStore:
    def __init__(self, state: Any, clock: Any, max_steps: int | None = None) -> None:
        self.state = state
        self.clock = clock
        self.max_steps = int(max_steps or rm.MAX_STEPS)  # WP-C3: 9 with REGISTER_V3

    def create(
        self,
        owner_user: str,
        source_kind: str,
        source_ref: str | None,
        values: dict[str, Any],
        suggestions: dict[str, Any],
    ) -> dict[str, Any]:
        if source_kind not in rm.SOURCE_KINDS:
            raise rm.RegisterError("source_kind", "unknown source")
        if len(self.list_mine(owner_user)) >= MAX_DRAFTS_OPEN:
            raise rm.RegisterError("draft", f"at most {MAX_DRAFTS_OPEN} open drafts; drop one")
        data = rm.empty_data()
        data["v"] = values
        data["sg"] = suggestions
        row = self.state.insert(
            "registration_draft",
            {
                "draft_id": "rd_" + secrets.token_hex(10),
                "owner_user": owner_user,
                "status": "draft",
                "step": 1,
                "source_kind": source_kind,
                "source_ref": source_ref,
                "data": json.dumps(data, sort_keys=True),
                "created_at": self.clock.now(),
            },
        )
        return _view(dict(row))

    def get(self, draft_id: str, owner_user: str) -> dict[str, Any]:
        if not rm.DRAFT_ID_RE.match(draft_id or ""):
            raise rm.RegisterError("draft_id", "is not a draft id")
        row = self.state.get("registration_draft", {"draft_id": draft_id})
        if row is None or row["owner_user"] != owner_user:
            raise rm.RegisterError("draft_id", "this draft does not exist")
        return _view(dict(row))

    def list_mine(self, owner_user: str, status: str = "draft") -> list[dict[str, Any]]:
        rows = self.state.query("registration_draft", {"owner_user": owner_user, "status": status})
        out = [_view(dict(r)) for r in rows]
        return sorted(out, key=lambda r: r["updated_at"], reverse=True)

    @staticmethod
    def is_empty(draft: dict[str, Any]) -> bool:
        """A blank draft the person has typed nothing into (the owner prefill does not count)."""
        d = draft["data"]
        typed = any(v not in ("", None, False) for k, v in d["v"].items() if k != "owner_user")
        return (
            draft["source_kind"] == "blank"
            and not typed
            and not d.get("q")
            and not d.get("off")
            and not d.get("repo_path")
        )

    def drop_empty(self, owner_user: str) -> int:
        """Abandon the empty blank drafts of one person (at most one stays: the new one)."""
        n = 0
        for d in self.list_mine(owner_user):
            if self.is_empty(d):
                self.save(d, status="abandoned")
                n += 1
        return n

    def save(
        self,
        draft: dict[str, Any],
        *,
        data: dict[str, Any] | None = None,
        step: int | None = None,
        status: str | None = None,
    ) -> dict[str, Any]:
        """Write a changed draft (the version read is the version expected)."""
        if draft["status"] != "draft":
            raise rm.RegisterError("draft_id", f"this draft is {draft['status']}")
        changes: dict[str, Any] = {}
        if data is not None:
            text = json.dumps(data, sort_keys=True)
            if len(text.encode("utf-8")) > MAX_DATA_BYTES:
                raise rm.RegisterError("draft", "holds too much text")
            changes["data"] = text
        if step is not None:
            changes["step"] = max(int(draft["step"]), min(self.max_steps, int(step)))
        if status is not None:
            if status not in rm.STATUSES:
                raise rm.RegisterError("status", "unknown status")
            changes["status"] = status
        if not changes:
            return draft
        try:
            row = self.state.update(
                "registration_draft",
                {"draft_id": draft["draft_id"]},
                changes,
                int(draft["row_version"]),
            )
        except ConcurrencyError:
            raise rm.RegisterError(
                "draft", "was changed in another window; reload the page"
            ) from None
        return _view(dict(row))

    def record_result(self, draft: dict[str, Any], result: dict[str, Any]) -> dict[str, Any]:
        """Keep what the submit did (for the result page) on the submitted draft."""
        if draft["status"] != "submitted":
            raise rm.RegisterError("draft_id", "this draft was not submitted")
        data = dict(draft["data"])
        data["result"] = result
        try:
            row = self.state.update(
                "registration_draft",
                {"draft_id": draft["draft_id"]},
                {"data": json.dumps(data, sort_keys=True)},
                int(draft["row_version"]),
            )
        except ConcurrencyError:
            return draft  # the result page then shows the system only
        return _view(dict(row))

    def release(self, draft: dict[str, Any]) -> None:
        """Give a claimed draft back (the submit wrote nothing)."""
        self.state.update(
            "registration_draft",
            {"draft_id": draft["draft_id"]},
            {"status": "draft"},
            int(draft["row_version"]),
        )

    def keep_system(self, draft: dict[str, Any], system_id: str) -> dict[str, Any]:
        """Note the new system id on a claimed (submitted) draft."""
        data = dict(draft["data"])
        data["result"] = {"system_id": system_id}
        row = self.state.update(
            "registration_draft",
            {"draft_id": draft["draft_id"]},
            {"data": json.dumps(data, sort_keys=True)},
            int(draft["row_version"]),
        )
        return _view(dict(row))

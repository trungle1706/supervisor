"""Reviews of an AI system (WP-G1, docs/governance.md section 10).

A review has a kind, a scope (agents, inventory nodes, systems), a reviewer, an optional window
and reports (file hash, link or note). ``complete`` locks it; a locked review cannot be edited;
``reopen`` needs a reason, unlocks it and is recorded (row and chain). Every change writes a
``review_change`` chain record (ids, enums, integers, hashes; no title, no report text, no
reason text, no user id). A completed review writes an ``outbound_event``.

Segregation of duties: the owner of the system cannot be the reviewer of its review.
"""

from __future__ import annotations

import json
import re
import uuid
from collections.abc import Mapping
from typing import Any

from supervisor.controls.model import actor_ref
from supervisor.core.canonical import format_ts, parse_ts, sha256_hex
from supervisor.core.errors import ConcurrencyError, NotFoundError
from supervisor.governance import events
from supervisor.governance.lifecycle import same
from supervisor.governance.model import (
    SegregationOfDuties,
    SystemsError,
    _text,
    check_ref_id,
    check_system_id,
    check_user,
    choice,
)
from supervisor.governance.systems import SystemService, _on, _plain

REVIEW_KINDS: tuple[str, ...] = ("internal", "external", "conformity", "classification_audit")
REVIEW_STATUSES: tuple[str, ...] = ("planned", "in_progress", "completed", "reopened")
SETTABLE_STATUSES: tuple[str, ...] = ("planned", "in_progress")  # completed: /complete
SCOPE_KINDS: tuple[str, ...] = ("agent", "node", "system", "event")  # event: WP-G5
REPORT_KINDS: tuple[str, ...] = ("file", "link", "note")
EDITABLE: tuple[str, ...] = (
    "kind",
    "title",
    "scope",
    "reviewer_user",
    "window_start",
    "window_end",
    "reports",
    "status",
)
MAX_TITLE = 200
MAX_REF = 500
MAX_SCOPE = 50
MAX_REPORTS = 50
MAX_REVIEWS = 500
# Roles that may complete or reopen a review that is not theirs (besides the named reviewer).
OVERRIDE_ROLES: tuple[str, ...] = ("admin",)
REOPEN_ROLES: tuple[str, ...] = ("admin", "approver")
_SHA = re.compile(r"^[0-9a-f]{64}$")


def _list(raw: Any) -> list[Any]:
    if isinstance(raw, (list, tuple)):
        return list(raw)
    try:
        val = json.loads(raw) if raw else []
    except (TypeError, ValueError):
        return []
    return val if isinstance(val, list) else []


def check_scope(value: Any) -> list[dict[str, str]]:
    if value is None or value == "":
        return []
    if not isinstance(value, (list, tuple)):
        raise SystemsError("scope must be a list of {kind, id}")
    if len(value) > MAX_SCOPE:
        raise SystemsError(f"scope has more than {MAX_SCOPE} entries")
    out: dict[tuple[str, str], dict[str, str]] = {}
    for item in value:
        if not isinstance(item, Mapping) or set(item) - {"kind", "id"}:
            raise SystemsError("each scope entry must be {kind, id}")
        kind = choice(item.get("kind"), SCOPE_KINDS, "scope kind")
        ident = check_ref_id(item.get("id"))
        out[(kind, ident)] = {"kind": kind, "id": ident}
    return [out[k] for k in sorted(out)]


def check_reports(value: Any) -> list[dict[str, str]]:
    if value is None or value == "":
        return []
    if not isinstance(value, (list, tuple)):
        raise SystemsError("reports must be a list of {kind, ref, sha256}")
    if len(value) > MAX_REPORTS:
        raise SystemsError(f"reports has more than {MAX_REPORTS} entries")
    out: list[dict[str, str]] = []
    for item in value:
        if not isinstance(item, Mapping) or set(item) - {"kind", "ref", "sha256"}:
            raise SystemsError("each report must be {kind, ref, sha256}")
        kind = choice(item.get("kind"), REPORT_KINDS, "report kind")
        ref = _text(item.get("ref"), "report ref", MAX_REF, required=True) or ""
        sha = item.get("sha256")
        if sha in (None, ""):
            if kind == "file":
                raise SystemsError("a file report needs the sha256 of the file")
            sha = sha256_hex({"note": ref}) if kind == "note" else ""
        elif not isinstance(sha, str) or not _SHA.match(sha.lower()):
            raise SystemsError("sha256 must be 64 hexadecimal characters")
        if kind == "link" and not ref.lower().startswith(("https://", "http://")):
            raise SystemsError("a link report must start with https:// or http://")
        out.append({"kind": kind, "ref": ref, "sha256": str(sha).lower()})
    return out


def check_window(value: Any, what: str) -> Any:
    if value is None or value == "":
        return None
    if not isinstance(value, str):
        raise SystemsError(f"{what} must be an RFC 3339 timestamp")
    try:
        return parse_ts(value)
    except ValueError:
        raise SystemsError(f"{what} must be an RFC 3339 timestamp") from None


def normalise(name: str, value: Any) -> Any:
    if name == "kind":
        return choice(value, REVIEW_KINDS, "kind")
    if name == "title":
        return _text(value, "title", MAX_TITLE, required=True)
    if name == "scope":
        return check_scope(value)
    if name == "reviewer_user":
        return check_user(value, "reviewer_user")
    if name in ("window_start", "window_end"):
        return check_window(value, name)
    if name == "reports":
        return check_reports(value)
    if name == "status":
        return choice(value, SETTABLE_STATUSES, "status")
    raise SystemsError(f"unknown field {name}")


class ReviewService:
    def __init__(self, systems: SystemService) -> None:
        self.systems = systems

    @classmethod
    def from_adapters(cls, adapters: Any, evidence: Any = None) -> ReviewService:
        return cls(SystemService.from_adapters(adapters, evidence=evidence))

    @property
    def state(self) -> Any:
        return self.systems.state

    # ------------------------------------------------------------------ plumbing
    def _ref(self, user: str) -> str:
        return actor_ref(self.systems.settings, user, "system")

    def _view(self, row: Mapping[str, Any]) -> dict[str, Any]:
        out = dict(row)
        out["scope"] = _list(row.get("scope"))
        out["reports"] = _list(row.get("reports"))
        out["locked"] = _on(row.get("locked"))
        return _plain(out)  # type: ignore[no-any-return]

    def _need(self, system_id: str, review_id: str) -> dict[str, Any]:
        check_system_id(system_id)
        if not isinstance(review_id, str) or not review_id.startswith("rv_"):
            raise NotFoundError(f"review {str(review_id)[:64]} does not exist")
        row = self.state.get("review", {"review_id": review_id})
        if row is None or row["system_id"] != system_id:
            raise NotFoundError(f"review {review_id[:64]} does not exist")
        return dict(row)

    def _chain(self, action: str, row: Mapping[str, Any], actor: str, **extra: Any) -> None:
        scope, reports = _list(row.get("scope")), _list(row.get("reports"))
        payload: dict[str, Any] = {
            "review_id": row["review_id"],
            "system_id": row["system_id"],
            "action": action,
            "kind": row["kind"],
            "status": row["status"],
            "locked": 1 if _on(row.get("locked")) else 0,
            "scope_n": len(scope),
            "reports_n": len(reports),
            "scope_hash": sha256_hex(scope),
            "reports_hash": sha256_hex(reports),
            "reopen_count": int(row.get("reopen_count") or 0),
            "actor_ref": self._ref(actor),
            "reviewer_ref": self._ref(str(row["reviewer_user"])),
            "ts": format_ts(self.systems.clock.now()),
            **extra,
        }
        self.systems._chain("review_change", f"system:{row['system_id']}", payload)

    def _check_reviewer(self, sys_row: Mapping[str, Any], reviewer: str) -> None:
        if same(reviewer, str(sys_row["owner_user"])) or any(
            same(reviewer, m["user_id"]) and m["team_role"] == "system_owner"
            for m in self.systems._team_rows(str(sys_row["system_id"]))
        ):
            raise SegregationOfDuties(
                "segregation of duties: the owner of the system cannot be the reviewer "
                "of its review"
            )

    # ------------------------------------------------------------------ reads
    def list_reviews(self, system_id: str) -> list[dict[str, Any]]:
        check_system_id(system_id)
        self.systems._need(system_id)
        rows = [dict(r) for r in self.state.query("review", {"system_id": system_id})]
        rows.sort(key=lambda r: (r["created_at"], r["review_id"]))
        return [self._view(r) for r in rows]

    def get(self, system_id: str, review_id: str) -> dict[str, Any]:
        self.systems._need(system_id)
        return self._view(self._need(system_id, review_id))

    # ------------------------------------------------------------------ writes
    def create(self, system_id: str, data: Mapping[str, Any], actor: str) -> dict[str, Any]:
        check_user(actor, "actor")
        sys_row = self.systems._need_open(system_id)
        unknown = sorted(set(data) - set(EDITABLE))
        if unknown:
            raise SystemsError(f"unknown field: {', '.join(unknown)}")
        missing = [f for f in ("kind", "title", "reviewer_user") if data.get(f) in (None, "")]
        if missing:
            raise SystemsError(f"required: {', '.join(missing)}")
        if data.get("status") not in (None, "", "planned"):
            raise SystemsError("a new review starts as planned")
        fields = {f: normalise(f, data.get(f)) for f in EDITABLE if f != "status"}
        self._check_window(fields)
        self._check_reviewer(sys_row, fields["reviewer_user"])
        if len(self.state.query("review", {"system_id": system_id})) >= MAX_REVIEWS:
            raise SystemsError(f"a system can have at most {MAX_REVIEWS} reviews")
        row = dict(
            self.state.insert(
                "review",
                {
                    **fields,
                    "review_id": "rv_" + uuid.uuid4().hex[:24],
                    "system_id": system_id,
                    "status": "planned",
                    "locked": False,
                    "reopen_count": 0,
                    "created_at": self.systems.clock.now(),
                    "created_by": actor,
                },
            )
        )
        self._chain("create", row, actor)
        return self._view(row)

    @staticmethod
    def _check_window(fields: Mapping[str, Any]) -> None:
        start, end = fields.get("window_start"), fields.get("window_end")
        try:
            late = start is not None and end is not None and start > end
        except TypeError:  # a naive and an aware value: the store gives UTC in both cases
            late = False
        if late:
            raise SystemsError("window_start must not be later than window_end")

    def update(
        self,
        system_id: str,
        review_id: str,
        changes: Mapping[str, Any],
        actor: str,
        expected_version: int | None = None,
    ) -> dict[str, Any]:
        check_user(actor, "actor")
        sys_row = self.systems._need_open(system_id)
        cur = self._need(system_id, review_id)
        if _on(cur["locked"]):
            raise SystemsError("the review is completed and locked; reopen it with a reason first")
        unknown = sorted(set(changes) - set(EDITABLE))
        if unknown:
            raise SystemsError(f"cannot change: {', '.join(unknown)}")
        if not changes:
            raise SystemsError("nothing to change")
        fields = {k: normalise(k, v) for k, v in changes.items()}
        self._check_window({**cur, **fields})
        if "reviewer_user" in fields:
            self._check_reviewer(sys_row, fields["reviewer_user"])
        version = expected_version if expected_version is not None else cur["row_version"]
        try:
            stored = dict(
                self.state.update("review", {"review_id": review_id}, fields, int(version))
            )
        except ConcurrencyError:
            raise SystemsError("the review was changed by someone else; reload and retry") from None
        self._chain("update", stored, actor, fields_n=len(fields))
        return self._view(stored)

    def _may(self, who: Any, row: Mapping[str, Any], roles: tuple[str, ...]) -> bool:
        held = set(getattr(who, "roles", ()) or ())
        return same(str(getattr(who, "user_id", "")), str(row["reviewer_user"])) or bool(
            held & set(roles)
        )

    def complete(self, system_id: str, review_id: str, who: Any) -> dict[str, Any]:
        """Complete and lock a review. The named reviewer (or an admin) does it."""
        actor = check_user(str(getattr(who, "user_id", "")), "actor")
        self.systems._need_open(system_id)
        cur = self._need(system_id, review_id)
        if cur["status"] == "completed":
            raise SystemsError("the review is already completed")
        if not self._may(who, cur, OVERRIDE_ROLES):
            raise SystemsError("only the reviewer of this review, or an admin, can complete it")
        try:
            stored = dict(
                self.state.update(
                    "review",
                    {"review_id": review_id},
                    {
                        "status": "completed",
                        "locked": True,
                        "completed_at": self.systems.clock.now(),
                        "completed_by": actor,
                    },
                    int(cur["row_version"]),
                )
            )
        except ConcurrencyError:
            raise SystemsError("the review was changed by someone else; reload and retry") from None
        self._chain("complete", stored, actor)
        events.emit(
            self.state,
            self.systems.clock,
            self.systems.settings,
            "review_completed",
            system_id,
            {"review_id": review_id, "review_kind": str(stored["kind"])},
        )
        return self._view(stored)

    def reopen(self, system_id: str, review_id: str, who: Any, reason: Any) -> dict[str, Any]:
        """Unlock a completed review. Needs a reason; recorded in the row and on the chain."""
        actor = check_user(str(getattr(who, "user_id", "")), "actor")
        self.systems._need_open(system_id)
        cur = self._need(system_id, review_id)
        text = _text(reason, "reason", 1000, required=True) or ""
        if cur["status"] != "completed":
            raise SystemsError("only a completed review can be reopened")
        if not self._may(who, cur, REOPEN_ROLES):
            raise SystemsError(
                "only the reviewer of this review, an approver or an admin can reopen it"
            )
        try:
            stored = dict(
                self.state.update(
                    "review",
                    {"review_id": review_id},
                    {
                        "status": "reopened",
                        "locked": False,
                        "reopen_reason": text,
                        "reopen_count": int(cur.get("reopen_count") or 0) + 1,
                    },
                    int(cur["row_version"]),
                )
            )
        except ConcurrencyError:
            raise SystemsError("the review was changed by someone else; reload and retry") from None
        self._chain("reopen", stored, actor, reason_hash=sha256_hex({"reason": text}))
        return self._view(stored)

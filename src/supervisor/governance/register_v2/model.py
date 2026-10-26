"""Fields, steps and validation of the register workflow v2 (WP-N3). Pure: no I/O."""

from __future__ import annotations

import json
import re
from collections.abc import Mapping
from typing import Any

from supervisor.core.errors import SupervisorError
from supervisor.governance import model as gm

STEPS = 6
KINDS: tuple[str, ...] = ("app", "endpoint", "genie", "job", "other")
SOURCE_KINDS: tuple[str, ...] = ("scan", "policy", "blank")
STATUSES: tuple[str, ...] = ("draft", "submitted", "abandoned")
SOURCES: tuple[str, ...] = ("scan", "policy", "person")

STEP1: tuple[str, ...] = ("name", "kind", "agent_id", "owner_user", "owner_team", "description")
STEP2: tuple[str, ...] = (
    "purpose",
    "system_type",
    "org_role",
    "user_segment",
    "personal_data",
    "human_control",
    "autonomy_level",
    "money_movement",
    "credit_decision",
    "model_family",
    "data_sources",
)
FIELDS_OF_STEP: dict[int, tuple[str, ...]] = {1: STEP1, 2: STEP2}
CHOICES: dict[str, tuple[str, ...]] = {
    "kind": KINDS,
    "system_type": gm.SYSTEM_TYPES,
    "org_role": gm.ORG_ROLES,
    "user_segment": gm.USER_SEGMENTS,
    "personal_data": gm.PERSONAL_DATA,
    "human_control": gm.HUMAN_CONTROLS,
    "autonomy_level": tuple(x for x in gm.AUTONOMY_LEVELS if x != "unspecified"),
}
BOOLS: tuple[str, ...] = ("money_movement", "credit_decision")
# fields that must be filled to leave the step (a saved-for-later draft may leave them blank)
REQUIRED: dict[int, tuple[str, ...]] = {
    1: ("name", "kind", "owner_user", "owner_team"),
    2: ("purpose", "system_type", "org_role", "user_segment", "personal_data", "human_control"),
}
MAX_DESC = 500
MAX_LIST = 600
MAX_REPO = 512
MAX_ANSWER_WHY = 500
ID_RE = re.compile(r"^[A-Za-z0-9_.:@-]{1,128}$")
SLUG_RE = re.compile(r"^[A-Za-z0-9_.:@/+-]{1,64}$")
DRAFT_ID_RE = re.compile(r"^rd_[0-9a-f]{20}$")


class RegisterError(SupervisorError):
    """Bad input of the register workflow (HTTP 400). The message starts with the field name."""

    def __init__(self, field: str, message: str) -> None:
        super().__init__(f"{field}: {message}")
        self.field = field


def on(value: Any) -> bool:
    if isinstance(value, str):
        return value.strip().lower() in ("1", "true", "on", "yes")
    return bool(value)


def json_of(value: Any, default: Any) -> Any:
    if isinstance(value, (dict, list)):
        return value
    try:
        out = json.loads(value) if value else default
    except (TypeError, ValueError):
        return default
    return out


def empty_data() -> dict[str, Any]:
    return {"v": {}, "sg": {}, "repo_path": "", "q": {}, "off": [], "off_why": {}}


def clean_field(name: str, raw: Any) -> Any:
    """One field of step 1 or 2 from a form value. ``''`` stays ``''`` (not set); a bad value
    is a RegisterError that names the field."""
    if name in BOOLS:
        return on(raw)
    text = "" if raw is None else str(raw).strip()
    if not text:
        return ""
    if any(ord(c) < 32 and c not in "\n\t" for c in text):
        raise RegisterError(name, "must not hold control characters")
    if name in CHOICES:
        if text not in CHOICES[name]:
            raise RegisterError(name, f"must be one of {', '.join(CHOICES[name])}")
        return text
    if name in ("name", "owner_user", "owner_team", "purpose"):
        try:
            return gm.normalise_field(name, text)
        except gm.SystemsError as exc:
            msg = str(exc)
            raise RegisterError(name, msg) from None
    if name == "agent_id":
        if not ID_RE.match(text):
            raise RegisterError(name, "must match ^[A-Za-z0-9_.:@-]{1,128}$")
        return text
    if name == "model_family":
        if not SLUG_RE.match(text):
            raise RegisterError(name, f"must match {SLUG_RE.pattern}")
        return text
    if name == "description":
        if len(text) > MAX_DESC:
            raise RegisterError(name, f"at most {MAX_DESC} characters")
        return text
    if name == "data_sources":
        if len(text) > MAX_LIST:
            raise RegisterError(name, f"at most {MAX_LIST} characters")
        return text
    raise RegisterError(name, "unknown field")


def clean_step(
    step: int, form: Mapping[str, str], current: Mapping[str, Any], *, strict: bool
) -> dict[str, Any]:
    """The values of one step from a form. ``strict`` (going forward): the required fields of
    the step must be filled. A field that is not in the form keeps its current value, except a
    checkbox of step 2 (a missing box means off)."""
    fields = FIELDS_OF_STEP.get(step, ())
    out: dict[str, Any] = {}
    for f in fields:
        if f in BOOLS:
            out[f] = on(form.get(f, ""))
        elif f in form:
            out[f] = clean_field(f, form[f])
        else:
            out[f] = current.get(f, "")
    if strict:
        missing = [f for f in REQUIRED.get(step, ()) if out.get(f) in ("", None)]
        if missing:
            raise RegisterError(missing[0], "is required")
    return out

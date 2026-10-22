"""AI system model (WP-G0): vocabularies and validation.

Pure Python. No SQL, no web, no Databricks imports. The unit of governance is the AI system:
a few unambiguous intake fields (the design rule of the Saidot handbook, p.24); everything else
is inherited from linked components or set by rules later.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from typing import Any

from supervisor.core.errors import SupervisorError

SYSTEM_TYPES: tuple[str, ...] = ("assistant", "decision", "automation", "platform", "feature")
ORG_ROLES: tuple[str, ...] = ("provider", "deployer", "both")
USER_SEGMENTS: tuple[str, ...] = ("internal", "customer", "partner")
PERSONAL_DATA: tuple[str, ...] = ("none", "identifiable", "pseudonymised", "special")
HUMAN_CONTROLS: tuple[str, ...] = ("pre_approval", "post_review", "none")
LIFECYCLE_STAGES: tuple[str, ...] = (
    "initiation",
    "design",
    "validation",
    "deployment",
    "operation",
    "re_evaluation",
    "retirement",
)
# Order matters: index = rank. unspecified ranks below low; prohibited above high.
RISK_LEVELS: tuple[str, ...] = ("unspecified", "low", "medium", "high", "prohibited")
RISK_RANK: dict[str, int] = {lv: i for i, lv in enumerate(RISK_LEVELS)}
RISK_SOURCES: tuple[str, ...] = ("manual", "inherited", "classifier")
# A person may record only these; "inherited" is a result, computed on read.
SETTABLE_RISK_SOURCES: tuple[str, ...] = ("manual", "classifier")
DECISION33_CLASSES: tuple[str, ...] = ("high_risk", "not_high_risk", "unclassified")
BUSINESS_IMPACTS: tuple[str, ...] = ("high", "medium", "low", "unspecified")
STATUSES: tuple[str, ...] = ("draft", "active", "archived")
TEAM_ROLES: tuple[str, ...] = (
    "system_owner",
    "business_owner",
    "technical_specialist",
    "data_steward",
    "compliance_specialist",
    "reviewer",
    "oversight_manager",
)
# These two team roles may not be held by the owner of the same system (segregation of duties).
SOD_ROLES: tuple[str, ...] = ("reviewer", "oversight_manager")
REF_KINDS: tuple[str, ...] = ("agent", "node")
LINK_ROLES: tuple[str, ...] = ("component_of", "built_on", "depends_on")
LINK_SOURCES: tuple[str, ...] = ("manual", "onboarding", "workspace_scan", "gate")
# Inventory level -> system level. The inventory has "critical"; a system is "high" at most by
# inheritance ("prohibited" is a legal finding a person sets, never inherited).
INVENTORY_TO_SYSTEM: dict[str, str] = {
    "low": "low",
    "medium": "medium",
    "high": "high",
    "critical": "high",
}

MAX_NAME = 120
MAX_PURPOSE = 2000
MAX_TEXT = 2000
MAX_TEAM = 128
MAX_TAGS = 20
MAX_MEMBERS = 200
MAX_LINKS = 500
_ID = re.compile(r"^[A-Za-z0-9_.:@-]{1,128}$")
_SYSTEM_ID = re.compile(r"^[A-Za-z0-9_.:-]{1,64}$")
_TAG_KEY = re.compile(r"^[A-Za-z0-9_.:-]{1,40}$")
_CTRL = re.compile(r"[\x00-\x1f\x7f]")

# Fields of the intake form (register) and fields a person may change later.
REQUIRED: tuple[str, ...] = (
    "name",
    "owner_user",
    "owner_team",
    "purpose",
    "system_type",
    "org_role",
    "user_segment",
    "personal_data",
    "human_control",
)
EDITABLE: tuple[str, ...] = (
    "name",
    "owner_user",
    "owner_team",
    "business_owner",
    "purpose",
    "system_type",
    "org_role",
    "user_segment",
    "personal_data",
    "money_movement",
    "credit_decision",
    "human_control",
    "lifecycle_stage",
    "risk_level",
    "risk_level_source",
    "risk_justification",
    "decision33_class",
    "business_impact",
    "status",
    "tags",
)


class SystemsError(SupervisorError):
    """Bad AI system input or an operation the service refuses (HTTP 400 at a route)."""


class SegregationOfDuties(SystemsError):
    """A role combination the segregation-of-duties rule refuses. The message starts with
    ``segregation of duties:``."""


class GovernanceOff(SystemsError):
    """GOVERNANCE_ENABLED is off (HTTP 400)."""


def ensure_on(settings: Any) -> None:
    """GovernanceOff (HTTP 400) unless GOVERNANCE_ENABLED is on."""
    if not getattr(settings, "governance_enabled", False):
        raise GovernanceOff("AI systems are off (GOVERNANCE_ENABLED=1 turns them on)")


def check_user(value: Any, what: str = "user") -> str:
    if not isinstance(value, str) or not _ID.match(value):
        raise SystemsError(f"{what} must be 1 to 128 characters from A-Z a-z 0-9 _ . : @ -")
    return value


def check_system_id(value: Any) -> str:
    if not isinstance(value, str) or not _SYSTEM_ID.match(value):
        raise SystemsError("system id must be 1 to 64 characters from A-Z a-z 0-9 _ . : -")
    return value


def check_ref_id(value: Any) -> str:
    if not isinstance(value, str) or not _ID.match(value):
        raise SystemsError("ref_id must be 1 to 128 characters from A-Z a-z 0-9 _ . : @ -")
    return value


def choice(value: Any, allowed: tuple[str, ...], what: str) -> str:
    if not isinstance(value, str) or value not in allowed:
        raise SystemsError(f"{what} must be one of {', '.join(allowed)}")
    return value


def _text(value: Any, what: str, limit: int, *, required: bool = False) -> str | None:
    if value is None or value == "":
        if required:
            raise SystemsError(f"{what} is required")
        return None
    if not isinstance(value, str):
        raise SystemsError(f"{what} must be text")
    text = value.strip()
    if _CTRL.search(text.replace("\n", " ").replace("\t", " ")):
        raise SystemsError(f"{what} has a control character")
    if len(text) > limit:
        raise SystemsError(f"{what} is longer than {limit} characters")
    if required and not text:
        raise SystemsError(f"{what} is required")
    return text or None


def _bool(value: Any, what: str) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        low = value.strip().lower()
        if low in ("1", "true", "yes", "on"):
            return True
        if low in ("0", "false", "no", "off", ""):
            return False
    raise SystemsError(f"{what} must be true or false")


def check_tags(value: Any) -> dict[str, str]:
    if value is None or value == "":
        return {}
    if not isinstance(value, Mapping):
        raise SystemsError("tags must be an object of short text values")
    if len(value) > MAX_TAGS:
        raise SystemsError(f"tags has more than {MAX_TAGS} entries")
    out: dict[str, str] = {}
    for k, v in value.items():
        if not isinstance(k, str) or not _TAG_KEY.match(k):
            raise SystemsError("a tag name must be 1 to 40 characters from A-Z a-z 0-9 _ . : -")
        if isinstance(v, bool) or not isinstance(v, (str, int)):
            raise SystemsError("a tag value must be text or a whole number")
        out[k] = _text(str(v), "tag value", 120) or ""
    return dict(sorted(out.items()))


_CHOICES: dict[str, tuple[str, ...]] = {
    "system_type": SYSTEM_TYPES,
    "org_role": ORG_ROLES,
    "user_segment": USER_SEGMENTS,
    "personal_data": PERSONAL_DATA,
    "human_control": HUMAN_CONTROLS,
    "lifecycle_stage": LIFECYCLE_STAGES,
    "risk_level": RISK_LEVELS,
    "risk_level_source": SETTABLE_RISK_SOURCES,
    "decision33_class": DECISION33_CLASSES,
    "business_impact": BUSINESS_IMPACTS,
    "status": ("draft", "active"),
}


def normalise_field(name: str, value: Any) -> Any:
    """Validate one field and return the value to store."""
    if name == "name":
        return _text(value, "name", MAX_NAME, required=True)
    if name == "owner_user":
        return check_user(value, "owner_user")
    if name == "owner_team":
        return _text(value, "owner_team", MAX_TEAM, required=True)
    if name == "business_owner":
        return None if value in (None, "") else check_user(value, "business_owner")
    if name == "purpose":
        return _text(value, "purpose", MAX_PURPOSE, required=True)
    if name == "risk_justification":
        return _text(value, "risk_justification", MAX_TEXT)
    if name in ("money_movement", "credit_decision"):
        return _bool(value, name)
    if name == "tags":
        return check_tags(value)
    if name in _CHOICES:
        return choice(value, _CHOICES[name], name)
    raise SystemsError(f"unknown field {name}")


_DEFAULTS: dict[str, Any] = {
    "business_owner": None,
    "money_movement": False,
    "credit_decision": False,
    "lifecycle_stage": "initiation",
    "risk_level": "unspecified",
    "risk_level_source": "manual",
    "risk_justification": None,
    "decision33_class": "unclassified",
    "business_impact": "unspecified",
    "tags": {},
}


def normalise_draft(data: Mapping[str, Any]) -> dict[str, Any]:
    """Validate an intake draft and return the row fields (no id, no timestamps). Status is
    always ``draft`` at registration."""
    unknown = sorted(set(data) - set(EDITABLE))
    if unknown:
        raise SystemsError(f"unknown field: {', '.join(unknown)}")
    if data.get("status") not in (None, "", "draft"):
        raise SystemsError("a new system starts as draft")
    missing = [f for f in REQUIRED if data.get(f) in (None, "")]
    if missing:
        raise SystemsError(f"required: {', '.join(missing)}")
    out: dict[str, Any] = {}
    for f in EDITABLE:
        if f == "status":
            continue
        raw = data.get(f)
        if raw is None:
            raw = _DEFAULTS.get(f)
        out[f] = normalise_field(f, raw)
    out["status"] = "draft"
    return out


def rank(level: str | None) -> int:
    return RISK_RANK.get(level or "unspecified", 0)


def max_level(*levels: str | None) -> str:
    best = "unspecified"
    for lv in levels:
        if lv is not None and rank(lv) > rank(best):
            best = lv
    return best

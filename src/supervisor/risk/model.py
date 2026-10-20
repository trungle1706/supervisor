"""Risk register model (WP29, ADR D26): vocabularies, scoring, validation.

Pure Python. No SQL, no web, no Databricks imports. Everything numeric is an integer:
likelihood and impact are 1 to 5, the score is their product (1 to 25), a band is one of
``low | medium | high | critical`` (the same four names as the inventory risk levels, so the
inventory graph code can carry them). The band thresholds are ILLUSTRATIVE until the bank sets
its own (``config/risk.yaml``).
"""

from __future__ import annotations

import datetime as dt
import re
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from supervisor.core.errors import SupervisorError

CATEGORIES: tuple[str, ...] = (
    "money_movement",
    "credit_decision",
    "pii",
    "injection",
    "model_behaviour",
    "availability",
    "third_party",
)
TREATMENTS: tuple[str, ...] = ("avoid", "mitigate", "accept", "transfer")
STATUSES: tuple[str, ...] = ("draft", "active", "retired")
SOURCES: tuple[str, ...] = ("manual", "import", "starter")
# matrix = a compliance matrix row (an obligation id); rule = a gate rule id; pack = an
# assurance pack id; monitor = a monitor name (controls.yaml); case = a case id; control = a
# WP30 catalogue control id (the evidence rule looks through it at the control's own sources).
LINK_KINDS: tuple[str, ...] = ("matrix", "rule", "pack", "monitor", "case", "control")
# Link kinds that count as a control for the evidence rule. matrix and case are references.
CONTROL_KINDS: tuple[str, ...] = ("rule", "pack", "monitor", "control")
BANDS: tuple[str, ...] = ("low", "medium", "high", "critical")
BAND_RANK: dict[str | None, int] = {None: 0, **{b: i + 1 for i, b in enumerate(BANDS)}}

LIKELIHOOD_NAMES = ("rare", "unlikely", "likely", "very likely", "almost certain")
IMPACT_NAMES = ("negligible", "minor", "moderate", "major", "severe")

_ID = re.compile(r"^[A-Za-z0-9_.:-]{1,64}$")
_TARGET = re.compile(r"^[A-Za-z0-9_.:@/-]{1,128}$")
MAX_TITLE = 200
MAX_TEXT = 2000
MAX_OWNER = 128

DEFAULT_CONFIG = Path(__file__).resolve().parents[3] / "config" / "risk.yaml"


class RiskError(SupervisorError):
    """Bad risk input or an operation the register refuses (HTTP 400 at a route)."""


class RiskOff(RiskError):
    """RISK_REGISTER_ENABLED is off (HTTP 400)."""


def ensure_on(settings: Any) -> None:
    """RiskOff (HTTP 400) unless RISK_REGISTER_ENABLED is on."""
    if not settings.risk_register_enabled:
        raise RiskOff(
            "The risk register is off (RISK_REGISTER_ENABLED=1 turns it on); "
            "python -m supervisor.risk import config/risks fills it"
        )


@dataclass(frozen=True)
class Thresholds:
    """Score -> band. ILLUSTRATIVE: the bank sets the real appetite (config/risk.yaml).

    ``score <= low_max`` is low, ``<= medium_max`` medium, ``<= high_max`` high, else critical.
    """

    low_max: int = 4
    medium_max: int = 9
    high_max: int = 15
    illustrative: bool = True

    def __post_init__(self) -> None:
        if not 1 <= self.low_max < self.medium_max < self.high_max < 25:
            raise RiskError("band thresholds must satisfy 1 <= low < medium < high < 25")

    def band(self, score: int) -> str:
        if score <= self.low_max:
            return "low"
        if score <= self.medium_max:
            return "medium"
        if score <= self.high_max:
            return "high"
        return "critical"


@dataclass(frozen=True)
class RiskConfig:
    thresholds: Thresholds = Thresholds()
    # Linked controls that must show "working" in the last window before evidence may lower
    # a residual score (ILLUSTRATIVE).
    min_working_controls: int = 1
    # A risk is "review_overdue" this many days after its review_date.
    review_grace_days: int = 0


def _int(value: Any, what: str, *, low: int = 1, high: int = 1000) -> int:
    """A real int in range. bool, float and numeric strings are refused."""
    if isinstance(value, bool) or not isinstance(value, int):
        raise RiskError(f"{what} must be a whole number")
    if not low <= value <= high:
        raise RiskError(f"{what} must be between {low} and {high}")
    return value


def load_config(path: Path | str | None = None) -> RiskConfig:
    """Read ``config/risk.yaml``. A missing file gives the defaults; a bad file is a RiskError."""
    p = Path(path) if path else DEFAULT_CONFIG
    if not p.is_file():
        return RiskConfig()
    try:
        doc = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
    except (OSError, yaml.YAMLError) as exc:
        raise RiskError(f"{p.name}: cannot read the risk config ({type(exc).__name__})") from None
    if not isinstance(doc, Mapping):
        raise RiskError(f"{p.name}: the risk config must be a mapping")
    bands = doc.get("bands") or {}
    ev = doc.get("evidence") or {}
    th = Thresholds(
        low_max=_int(bands.get("low_max", 4), "bands.low_max"),
        medium_max=_int(bands.get("medium_max", 9), "bands.medium_max"),
        high_max=_int(bands.get("high_max", 15), "bands.high_max"),
        illustrative=bool(doc.get("illustrative", True)),
    )
    return RiskConfig(
        th,
        _int(ev.get("min_working_controls", 1), "evidence.min_working_controls", low=1),
        _int(doc.get("review_grace_days", 0), "review_grace_days", low=0),
    )


def score_of(likelihood: int, impact: int) -> int:
    """Likelihood x impact, both 1 to 5 whole numbers."""
    return _int(likelihood, "likelihood", high=5) * _int(impact, "impact", high=5)


def band_of(score: int, th: Thresholds | None = None) -> str:
    return (th or Thresholds()).band(score)


def max_band(*bands: str | None) -> str | None:
    best: str | None = None
    for b in bands:
        if BAND_RANK[b] > BAND_RANK[best]:
            best = b
    return best


def check_id(value: Any, what: str = "risk id") -> str:
    if not isinstance(value, str) or not _ID.match(value):
        raise RiskError(f"{what} must be 1 to 64 characters from A-Z a-z 0-9 _ . : -")
    return value


def check_target(kind: str, target: Any) -> str:
    if kind not in LINK_KINDS:
        raise RiskError(f"link kind must be one of {', '.join(LINK_KINDS)}")
    if not isinstance(target, str) or not _TARGET.match(target):
        raise RiskError("link target must be 1 to 128 characters from A-Z a-z 0-9 _ . : @ / -")
    return target


def _text(value: Any, what: str, limit: int, *, required: bool = False) -> str | None:
    if value is None or value == "":
        if required:
            raise RiskError(f"{what} is required")
        return None
    if not isinstance(value, str):
        raise RiskError(f"{what} must be text")
    text = value.strip()
    if len(text) > limit:
        raise RiskError(f"{what} is longer than {limit} characters")
    if required and not text:
        raise RiskError(f"{what} is required")
    return text or None


def parse_date(value: Any, what: str = "review_date") -> dt.date | None:
    if value is None or value == "":
        return None
    if isinstance(value, dt.datetime):
        return value.date()
    if isinstance(value, dt.date):
        return value
    if isinstance(value, str):
        try:
            return dt.date.fromisoformat(value.strip())
        except ValueError:
            pass
    raise RiskError(f"{what} must be a date like 2027-01-31")


def _choice(value: Any, allowed: tuple[str, ...], what: str) -> str:
    if not isinstance(value, str) or value not in allowed:
        raise RiskError(f"{what} must be one of {', '.join(allowed)}")
    return value


# Fields a person may change with an update.
EDITABLE: tuple[str, ...] = (
    "title",
    "description",
    "category",
    "agent_id",
    "node_id",
    "inherent_likelihood",
    "inherent_impact",
    "marginal_risk",
    "marginal_note",
    "treatment",
    "treatment_note",
    "residual_likelihood",
    "residual_impact",
    "owner",
    "review_date",
    "status",
)


def normalise(data: Mapping[str, Any], *, source: str = "manual") -> dict[str, Any]:
    """Validate a full risk record and return the row fields (no id, no timestamps).

    Raises RiskError with a message for the user. Refuses: a missing anchor, scores out of
    range, a residual above the inherent score on either axis, ``accept`` with a lowered
    residual or no justification, an active risk with no review date.
    """
    out: dict[str, Any] = {
        "title": _text(data.get("title"), "title", MAX_TITLE, required=True),
        "description": _text(data.get("description"), "description", MAX_TEXT) or "",
        "category": _choice(data.get("category"), CATEGORIES, "category"),
        "agent_id": _text(data.get("agent_id"), "agent_id", 64),
        "node_id": _text(data.get("node_id"), "node_id", 64),
        "inherent_likelihood": _int(data.get("inherent_likelihood"), "inherent_likelihood", high=5),
        "inherent_impact": _int(data.get("inherent_impact"), "inherent_impact", high=5),
        "marginal_risk": None,
        "marginal_note": _text(data.get("marginal_note"), "marginal_note", MAX_TEXT),
        "treatment": _choice(data.get("treatment"), TREATMENTS, "treatment"),
        "treatment_note": _text(data.get("treatment_note"), "treatment_note", MAX_TEXT),
        "owner": _text(data.get("owner"), "owner", MAX_OWNER, required=True),
        "review_date": parse_date(data.get("review_date")),
        "status": _choice(data.get("status", "draft"), STATUSES, "status"),
        "source": _choice(source, SOURCES, "source"),
    }
    if data.get("marginal_risk") not in (None, ""):
        out["marginal_risk"] = _int(data["marginal_risk"], "marginal_risk", high=5)
    if out["agent_id"] is not None:
        check_id(out["agent_id"], "agent_id")
    if out["node_id"] is not None:
        check_id(out["node_id"], "node_id")
    if out["agent_id"] is None and out["node_id"] is None:
        raise RiskError("a risk needs an agent_id or an inventory node_id")
    il, ii = out["inherent_likelihood"], out["inherent_impact"]
    rl = data.get("residual_likelihood")
    ri = data.get("residual_impact")
    out["residual_likelihood"] = il if rl in (None, "") else _int(rl, "residual_likelihood", high=5)
    out["residual_impact"] = ii if ri in (None, "") else _int(ri, "residual_impact", high=5)
    if out["residual_likelihood"] > il or out["residual_impact"] > ii:
        raise RiskError("residual likelihood and impact cannot be above the inherent values")
    if out["treatment"] == "accept":
        if (out["residual_likelihood"], out["residual_impact"]) != (il, ii):
            raise RiskError("treatment accept leaves the residual equal to the inherent score")
        if not out["treatment_note"]:
            raise RiskError("treatment accept needs a justification (treatment_note)")
    if out["status"] == "active" and out["review_date"] is None:
        raise RiskError("an active risk needs a review_date")
    return out

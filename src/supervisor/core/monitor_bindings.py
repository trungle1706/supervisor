"""Per-agent monitor bindings (WP1b-B, D06): which tool is the reply, the decision, the payment.

The quality, fairness, drift and multi-agent monitors used to know three demo tool names.
A binding says, for one agent, which of its tools each monitor reads. It lives in the agent
manifest (``monitors:`` key) and in the ``agents:`` section of ``policies/*.yaml`` (the
policy entry wins). Every field is optional; a field left out is derived from the tool risk
classes (see ``supervisor.monitors.bindings``), and when nothing can be derived the monitor
writes an explicit ``not_applicable`` status instead of staying silent.

Pure pydantic; no I/O. The model is strict: an unknown key is an error, so a typo in a
binding cannot silently switch a monitor off.
"""

from __future__ import annotations

import re
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

# Never sliced, whatever a binding says (same list as monitors/fairness.py).
FORBIDDEN_ATTRIBUTES = frozenset(
    {"ethnicity", "ethnic_group", "race", "religion", "dan_toc", "ton_giao", "faith"}
)


def _norm(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", name.strip().lower()).strip("_")


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class QualityBinding(_Strict):
    reply_tools: list[str] = Field(default_factory=list)  # tools whose call text is the output
    text_arg: str = "text"  # argument of the call that holds the output text


class FairnessBinding(_Strict):
    decision_tool: str | None = None  # the tool call that records approve / decline
    decision_arg: str | None = None
    subject_arg: str | None = None
    approve_values: list[str] = Field(default_factory=list)
    # attribute name -> argument key of the decision call that carries its value. Optional:
    # without it the global attribute source (config/fairness.yaml) is used.
    protected_attribute_keys: dict[str, str] = Field(default_factory=dict)

    @field_validator("protected_attribute_keys")
    @classmethod
    def _no_forbidden(cls, v: dict[str, str]) -> dict[str, str]:
        # Both sides are checked: {"group": "ethnicity"} would slice by ethnicity under
        # another name. "Dan-Toc", " religion " and "dan toc" normalise to the listed form.
        for name, arg_key in v.items():
            for side in (name, arg_key):
                if _norm(side) in FORBIDDEN_ATTRIBUTES:
                    raise ValueError(f"attribute {side!r} is never allowed in fairness slices")
        return {k.strip().lower(): val for k, val in v.items()}


class SplitPaymentBinding(_Strict):
    tool: str | None = None  # money tool the split-payment scan reads
    customer_key: str | None = None
    payee_key: str | None = None


class DriftBinding(_Strict):
    window_s: int | None = Field(default=None, ge=60)
    baseline_windows: int | None = Field(default=None, ge=2)
    min_baseline_windows: int | None = Field(default=None, ge=1)
    min_n: int | None = Field(default=None, ge=1)


# WP27 (ADR D29): the nine signals of the session monitor, in a fixed order, and the default
# weights (basis points, sum 10000). A policy may replace them; the sum is checked below.
# WP41 (ADR D33): a tenth signal, ``split_cue``. A policy that lists the nine older names keeps
# working: ``split_cue`` then has weight 0 (its hit still counts for K and for solo_signals).
SIGNALS: tuple[str, ...] = (
    "findings",
    "refusals",
    "expand",
    "drift",
    "money",
    "near_dup",
    "timing",
    "cross_agent",
    "memory",
    "split_cue",
)
LEGACY_SIGNALS: tuple[str, ...] = SIGNALS[:-1]
DEFAULT_WEIGHTS: dict[str, int] = {
    "findings": 1800,
    "refusals": 900,
    "expand": 1300,
    "drift": 800,
    "money": 1300,
    "near_dup": 800,
    "timing": 100,  # was 400 before split_cue: the harness numbers do not move (ADR D33)
    "cross_agent": 1300,
    "memory": 1400,
    "split_cue": 300,
}
PAUSE_SCOPES: tuple[str, ...] = ("money", "credit")


class DailyBinding(_Strict):
    """``monitors.session.daily`` (WP27 follow-up): a per-consumer window over a day, read by the
    batch job only. It sees slow attacks and a rotating ``session_id`` (the sessions share one
    consumer). Case only, never a pause. Off by default."""

    enabled: bool = False
    window_s: int = Field(default=86400, ge=3600, le=7 * 86400)
    k: int = Field(default=3, ge=1, le=8)
    case_threshold_bp: int = Field(default=2500, ge=1, le=10000)


class SessionBinding(_Strict):
    """``agents.<id>.monitors.session`` (WP27): per-agent settings of the session monitor.

    Every field is optional; a field left out takes the global ``SESSION_*`` setting or the
    built-in default. ``pause_scope`` empty (the default) means case only, no pause."""

    enabled: bool | None = None
    window_s: int | None = Field(default=None, ge=60, le=86400)
    k: int | None = Field(default=None, ge=1, le=8)
    cooldown_s: int | None = Field(default=None, ge=60, le=7 * 86400)
    hit_bp: int | None = Field(default=None, ge=1, le=10000)
    case_threshold_bp: int | None = Field(default=None, ge=1, le=10000)
    pause_threshold_bp: int | None = Field(default=None, ge=1, le=10000)
    pause_scope: list[Literal["money", "credit"]] | None = None
    weights: dict[str, int] | None = None
    # signals that open a case on their own, without K hits (default: memory, the state signal)
    solo_signals: list[str] | None = None
    cap_minor: int | None = Field(default=None, ge=1)
    daily: DailyBinding | None = None  # per-consumer daily window, batch only

    @field_validator("solo_signals")
    @classmethod
    def _solo(cls, v: list[str] | None) -> list[str] | None:
        if v is not None and any(s not in SIGNALS for s in v):
            raise ValueError(f"solo_signals may hold only: {', '.join(SIGNALS)}")
        return v

    @field_validator("weights")
    @classmethod
    def _weights(cls, v: dict[str, int] | None) -> dict[str, int] | None:
        if v is None:
            return v
        if set(v) == set(LEGACY_SIGNALS):  # WP41: a list from before split_cue
            v = {**v, "split_cue": 0}
        if set(v) != set(SIGNALS):
            raise ValueError(f"weights must name exactly these signals: {', '.join(SIGNALS)}")
        if any(isinstance(w, bool) or not isinstance(w, int) or w < 0 for w in v.values()):
            raise ValueError("weights are integers (basis points), zero or more")
        if sum(v.values()) != 10000:
            raise ValueError(f"weights must sum to 10000 bp, they sum to {sum(v.values())}")
        return {k: v[k] for k in SIGNALS}

    @model_validator(mode="after")
    def _thresholds(self) -> SessionBinding:
        if (
            self.pause_threshold_bp is not None
            and self.case_threshold_bp is not None
            and self.pause_threshold_bp < self.case_threshold_bp
        ):
            raise ValueError("pause_threshold_bp must not be below case_threshold_bp")
        if self.pause_scope and self.weights is not None:
            pause_bp = self.pause_threshold_bp if self.pause_threshold_bp is not None else 4000
            if self.weights["findings"] >= pause_bp:
                # R1: detector, Tier 0b and judge output is one counter and never pauses alone
                raise ValueError(
                    "the findings weight must stay below pause_threshold_bp: detector and "
                    "judge output may not pause a session on its own (rule R1)"
                )
        return self


class MonitorBindings(_Strict):
    quality: QualityBinding | None = None
    fairness: FairnessBinding | None = None
    split_payment: SplitPaymentBinding | None = None
    drift: DriftBinding | None = None
    session: SessionBinding | None = None  # WP27


__all__ = [
    "DEFAULT_WEIGHTS",
    "DailyBinding",
    "FORBIDDEN_ATTRIBUTES",
    "PAUSE_SCOPES",
    "SIGNALS",
    "SessionBinding",
    "DriftBinding",
    "FairnessBinding",
    "MonitorBindings",
    "QualityBinding",
    "SplitPaymentBinding",
]

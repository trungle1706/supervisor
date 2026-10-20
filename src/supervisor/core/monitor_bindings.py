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

from pydantic import BaseModel, ConfigDict, Field, field_validator

# Never sliced, whatever a binding says (same list as monitors/fairness.py).
FORBIDDEN_ATTRIBUTES = frozenset(
    {"ethnicity", "ethnic_group", "race", "religion", "dan_toc", "ton_giao", "faith"}
)


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
        for name in v:
            if name.strip().lower() in FORBIDDEN_ATTRIBUTES:
                raise ValueError(f"attribute {name!r} is never allowed in fairness slices")
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


class MonitorBindings(_Strict):
    quality: QualityBinding | None = None
    fairness: FairnessBinding | None = None
    split_payment: SplitPaymentBinding | None = None
    drift: DriftBinding | None = None


__all__ = [
    "FORBIDDEN_ATTRIBUTES",
    "DriftBinding",
    "FairnessBinding",
    "MonitorBindings",
    "QualityBinding",
    "SplitPaymentBinding",
]

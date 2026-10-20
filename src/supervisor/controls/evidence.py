"""Evidence status of a control (WP30, ADR D30): working, failing or no_data.

A control is judged per agent, in one window (the WP29 window: ``RISK_EVIDENCE_WINDOW_DAYS``
ending at the last full hour), from the SAME facts the risk register uses. The facts come from
``supervisor.risk.evidence.Collector``; this module adds no second way of counting.

Each runtime source of the control is asked once (``Collector.count`` with one link):

=========  ======================================================================================
rule       working = at least one tier-0 hit by the agent in the window; failing = the rule id
           is not in the deployed policy any more (a retired rule is no evidence); else idle
pack       newest non-mock result of the agent: ok = working, fail or error = failing, else idle
           (a mock result never counts)
monitor    newest daily status of the agent: ok = working, anything else idle
detector   reference only (counted in ``refs_n``)
document   reference only (counted in ``refs_n``)
=========  ======================================================================================

The status of the control:

* ``failing``: at least one runtime source is failing;
* ``working``: no source is failing and at least one is working;
* ``no_data``: everything else (all idle, only references, or no supervised agent). Quiet is not
  proof, and a design document is not behaviour.

An agent in SHADOW, RETIRED or unknown is not supervised: its facts are not evidence (the same
rule as WP29), so its controls are ``no_data``. Judges are not an input (rule R1). Every row
stores a fixed reason code and integer counts, never text (rule R2).
"""

from __future__ import annotations

from dataclasses import dataclass

from supervisor.controls.model import (
    REF_KINDS,
    RUNTIME_KINDS,
    STATUS_FAILING,
    STATUS_NO_DATA,
    STATUS_WORKING,
)
from supervisor.core.canonical import format_ts, sha256_hex
from supervisor.risk import evidence as ev

REASONS = (
    "sources_working",
    "source_failing",
    "no_working_source",
    "reference_only",
    "no_sources",
    "no_supervised_agent",
    "not_evaluated",
    "stale",
)

STALE_WINDOWS = ev.STALE_WINDOWS


@dataclass
class Result:
    status: str
    reason: str
    sources_n: int = 0
    working_n: int = 0
    failing_n: int = 0
    idle_n: int = 0
    refs_n: int = 0

    def counts(self) -> dict[str, int]:
        return {
            "sources_n": self.sources_n,
            "working_n": self.working_n,
            "failing_n": self.failing_n,
            "idle_n": self.idle_n,
            "refs_n": self.refs_n,
        }


def decide(sources_n: int, working_n: int, failing_n: int, refs_n: int, supervised: bool) -> Result:
    """Status and reason from the counts. Pure and deterministic."""
    idle_n = sources_n - working_n - failing_n
    base = Result("", "", sources_n, working_n, failing_n, idle_n, refs_n)
    if not supervised:
        base.status, base.reason = STATUS_NO_DATA, "no_supervised_agent"
    elif failing_n > 0:
        base.status, base.reason = STATUS_FAILING, "source_failing"
    elif working_n > 0:
        base.status, base.reason = STATUS_WORKING, "sources_working"
    elif sources_n > 0:
        base.status, base.reason = STATUS_NO_DATA, "no_working_source"
    elif refs_n > 0:
        base.status, base.reason = STATUS_NO_DATA, "reference_only"
    else:
        base.status, base.reason = STATUS_NO_DATA, "no_sources"
    return base


def evaluate(
    col: ev.Collector,
    agent_id: str,
    sources: list[tuple[str, str]],
    w: ev.Window,
) -> Result:
    """Status of one control for one agent in window ``w``. ``sources`` = (kind, target) pairs
    of the active control map (all evidence kinds)."""
    supervised, _ = col.split_agents([agent_id])
    refs_n = sum(1 for k, _t in sources if k in REF_KINDS)
    runtime = sorted({(k, t) for k, t in sources if k in RUNTIME_KINDS})
    if not supervised:
        return decide(len(runtime), 0, 0, refs_n, False)
    working = failing = 0
    for kind, target in runtime:
        c = col.count(supervised, [(kind, target)], w)
        if c.controls_failing:
            failing += 1
        elif c.controls_working:
            working += 1
    return decide(len(runtime), working, failing, refs_n, True)


def status_id(control_id: str, agent_id: str, w: ev.Window) -> str:
    return "cs_" + sha256_hex({"c": control_id, "a": agent_id, "end": format_ts(w.end)})[:24]


def status_digest(control_id: str, agent_id: str, w: ev.Window, r: Result) -> str:
    """Hash of the facts a row states. The same facts give the same hash."""
    return sha256_hex(
        {
            "control_id": control_id,
            "agent_id": agent_id,
            "window_start": format_ts(w.start),
            "window_end": format_ts(w.end),
            "status": r.status,
            "reason": r.reason,
            **r.counts(),
        }
    )


def compliance_bp(working: int, in_scope: int) -> int | None:
    """Integer basis points of controls with working evidence over controls in scope.
    ``None`` when no control is in scope (no claim, not 0 and not 10000)."""
    if in_scope <= 0:
        return None
    return working * 10000 // in_scope

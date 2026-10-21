"""Alert drills for the nine WP39 use cases (run by ``python -m supervisor.alerts.harness``).

A drill feeds one rule of ``config/alerts.yaml`` with synthetic signals and checks what a SOC
analyst on call relies on:

* it FIRES once when the condition holds (count or share reached);
* it stays QUIET just below the condition (one signal short, or a share just under the limit);
* repeats inside the dedupe window are SUPPRESSED (still one alert, ``suppressed_count`` exact);
* the SIEM event of the alert carries the correlation id of the trigger (when the signals have one);
* for rate rules, a sweep of scenarios on both sides of the limit gives counts and a Wilson 95
  percent interval for "fires above" and "quiet below".

Everything is deterministic (fixed seed, no clock, no store). Thresholds are ILLUSTRATIVE.
"""

from __future__ import annotations

import math
import random
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any

from supervisor.alerts.engine import evaluate
from supervisor.alerts.rules import Rule, RuleSet, load_rules
from supervisor.alerts.signals import Signal

T0 = datetime(2026, 10, 20, 8, 0, 0, tzinfo=UTC)
SEED = 20261020
SWEEP = 40  # scenarios per side of a rate limit
CORR = "corr-drill-0001"


@dataclass(frozen=True)
class Spec:
    """What a matching signal looks like and what the other signals of the source look like."""

    kind: str
    match: dict[str, Any]
    other: dict[str, Any] = field(default_factory=dict)
    group: str = "drill-agent"


SPECS: dict[str, Spec] = {
    "AL-COVERAGE-GAP": Spec(
        "coverage_gap", {"agent_id": "drill-agent", "seen_in": "trace", "registered": True}
    ),
    "AL-DETECTOR-FAILED": Spec(
        "gate_decision",
        {"agent_id": "drill-agent", "detector_failed": True, "status": "allow"},
        {"agent_id": "drill-agent", "detector_failed": False, "status": "allow"},
    ),
    "AL-THREAT-NOT-ENFORCED": Spec(
        "gate_finding",
        {
            "agent_id": "drill-agent",
            "code": "injection.ignore_previous",
            "finding_class": "injection",
            "direction": "input",
            "action_hint": "block",
            "enforcement": "shadow",
        },
        {
            "agent_id": "drill-agent",
            "code": "injection.ignore_previous",
            "finding_class": "injection",
            "direction": "input",
            "action_hint": "block",
            "enforcement": "enforced",
        },
    ),
    "AL-SECRETS-OUTPUT": Spec(
        "gate_finding",
        {
            "agent_id": "drill-agent",
            "code": "secret.api_key",
            "finding_class": "secret",
            "direction": "output",
        },
        {
            "agent_id": "drill-agent",
            "code": "secret.api_key",
            "finding_class": "secret",
            "direction": "input",
        },
    ),
    "AL-PII-OUTPUT": Spec(
        "gate_finding",
        {
            "agent_id": "drill-agent",
            "code": "pii.phone",
            "finding_class": "pii",
            "direction": "output",
        },
        {
            "agent_id": "drill-agent",
            "code": "pii.phone",
            "finding_class": "pii",
            "direction": "input",
        },
    ),
    "AL-REDACTION-SPIKE": Spec(
        "gate_decision",
        {"agent_id": "drill-agent", "status": "transform", "latency_us": 900},
        {"agent_id": "drill-agent", "status": "allow", "latency_us": 900},
    ),
    "AL-LATENCY-DEGRADATION": Spec(
        "gate_decision",
        {"agent_id": "drill-agent", "status": "allow", "latency_us": 90_000},
        {"agent_id": "drill-agent", "status": "allow", "latency_us": 4_000},
        group="*",
    ),
    "AL-ERROR-RATE": Spec(
        "gate_request",
        {"agent_id": "drill-agent", "outcome_class": "rejected_401"},
        {"agent_id": "drill-agent", "outcome_class": "ok"},
        group="*",
    ),
    "AL-INGRESS-AUTH-ANOMALY": Spec(
        "ingress_reject",
        {"agent_id": "drill-agent", "reason_code": "replayed_nonce"},
        {"agent_id": "drill-agent", "reason_code": "stale_timestamp"},
    ),
}
NINE = tuple(SPECS)


def wilson_bp(successes: int, n: int) -> tuple[int, int]:
    """Wilson 95 percent interval in integer basis points."""
    if n <= 0:
        return (0, 10000)
    z = 1.959964
    p = successes / n
    d = 1 + z * z / n
    c = (p + z * z / (2 * n)) / d
    h = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / d
    return max(0, math.floor((c - h) * 10000)), min(10000, math.ceil((c + h) * 10000))


class _NullState:
    """The row builder only asks the store for an open case of the agent."""

    def query(self, *_: Any, **__: Any) -> list[Any]:
        return []


def _sig(i: int, spec: Spec, fields: dict[str, Any], at: datetime, tag: str) -> Signal:
    return Signal(sid=f"{tag}:{i:05d}", kind=spec.kind, ts=at, fields=dict(fields))


def _spread(n: int, window_s: int) -> list[datetime]:
    """n instants inside one window, 1 s apart at most, in order."""
    step = max(0.001, min(1.0, (max(window_s, 1) - 1) / max(n, 1) / 2))
    return [T0 + timedelta(seconds=i * step) for i in range(n)]


def _run(rule: Rule, signals: list[Signal]) -> Any:
    rs = RuleSet(rules=(rule,), suppressions=(), config_hash="drill")
    return evaluate(rs, signals)


def _corr_fields(f: dict[str, Any], on: bool) -> dict[str, Any]:
    return {**f, "correlation_id": CORR} if on else dict(f)


def drill_rule(rule: Rule) -> dict[str, Any]:
    """Fire, quiet, suppress and SIEM checks for one rule (the sweep is separate)."""
    spec = SPECS[rule.id]
    carries_corr = rule.source in ("gate_decision", "gate_finding", "gate_request")
    match = _corr_fields(spec.match, carries_corr)
    other = _corr_fields(spec.other, carries_corr)
    window = rule.window_s
    n_match = rule.threshold
    n_total = n_match
    if rule.rate_min_bp is not None:
        # total large enough that the minimum count and the share can both be met
        n_total = max(rule.threshold * 4, 40)
        n_match = max(rule.threshold, math.ceil(n_total * rule.rate_min_bp / 10000) + 1)
    times = _spread(n_total, window)
    fire = [_sig(i, spec, match if i < n_match else other, times[i], "f") for i in range(n_total)]
    # the last signals are the matching ones, so the alert fires at the end of the window
    fire.sort(key=lambda s: (s.ts, s.sid))
    res = _run(rule, fire)
    fired = len(res.fired)

    # quiet: one matching signal short of the count
    short = max(0, rule.threshold - 1)
    quiet_sigs = [_sig(i, spec, match, times[i], "q") for i in range(short)]
    if spec.other:
        quiet_sigs += [
            _sig(100 + i, spec, other, times[min(i, n_total - 1)], "o")
            for i in range(n_total if rule.rate_min_bp is not None else 2)
        ]
    quiet_fired = len(_run(rule, quiet_sigs).fired)

    # suppress: more matching signals inside the dedupe window
    extra = 5
    later = fire[-1].ts + timedelta(seconds=1)  # inside the window and the dedupe time
    sigs = list(fire)
    for k in range(extra):
        # rate rules: matching signals keep the share above the limit
        sigs.append(_sig(500 + k, spec, match, later + timedelta(milliseconds=k), "r"))
    res2 = _run(rule, sigs)
    suppressed_ok = len(res2.fired) == 1 and res2.fired[0].suppressed_count >= 1

    # SIEM: the event of the alert carries the correlation id of the trigger
    siem_ok = True
    if res.fired:
        from supervisor.adapters.integrations.siem import event_from_alert
        from supervisor.alerts.service import AlertService

        svc = AlertService(_NullState(), None)  # type: ignore[arg-type]
        row = svc.row_for(res.fired[0])
        row = {**row, "ts": res.fired[0].ts, "first_ts": res.fired[0].first_ts}
        ev = event_from_alert(row)
        want = CORR if carries_corr else ""
        siem_ok = (ev.attrs or {}).get("correlation_id") == want and ev.rule_id == rule.id
    return {
        "rule_id": rule.id,
        "fires": fired == 1,
        "quiet": quiet_fired == 0,
        "suppressed": suppressed_ok,
        "siem_correlation": siem_ok,
        "signals": len(fire),
        "matching": n_match,
    }


def sweep_rate(rule: Rule) -> dict[str, Any] | None:
    """Rate rules only: SWEEP scenarios clearly above the limit must fire, SWEEP clearly below
    must not. Counts, rates in bp and Wilson intervals."""
    if rule.rate_min_bp is None:
        return None
    spec = SPECS[rule.id]
    rng = random.Random(SEED + sum(map(ord, rule.id)))  # noqa: S311 - fixed seed, not security
    above_fired = below_fired = 0
    limit = rule.rate_min_bp
    for _ in range(SWEEP):
        total = rng.randint(max(rule.threshold * 3, 30), 200)
        hi = max(rule.threshold, math.ceil(total * limit * 1.5 / 10000) + 1)
        lo_cap = max(0, math.floor(total * limit * 0.6 / 10000))
        for name, count in (("above", hi), ("below", rng.randint(0, lo_cap))):
            times = _spread(total, rule.window_s)
            sigs = [
                _sig(i, spec, spec.match if i >= total - count else spec.other, times[i], name)
                for i in range(total)
            ]
            n = len(_run(rule, sigs).fired)
            if name == "above":
                above_fired += n > 0
            else:
                below_fired += n > 0
    return {
        "rule_id": rule.id,
        "min_bp": limit,
        "scenarios_per_side": SWEEP,
        "fired_above": above_fired,
        "fired_above_bp": above_fired * 10000 // SWEEP,
        "fired_above_ci_bp": list(wilson_bp(above_fired, SWEEP)),
        "fired_below": below_fired,
        "quiet_below_bp": (SWEEP - below_fired) * 10000 // SWEEP,
        "quiet_below_ci_bp": list(wilson_bp(SWEEP - below_fired, SWEEP)),
    }


def storm(rule: Rule, n: int = 5000) -> dict[str, Any]:
    """An alert storm: n matching signals inside one dedupe window give ONE alert."""
    spec = SPECS[rule.id]
    times = [T0 + timedelta(milliseconds=i) for i in range(n)]
    sigs = [_sig(i, spec, spec.match, times[i], "s") for i in range(n)]
    if rule.rate_min_bp is not None:
        pass  # all signals match, so the share is 10000 bp
    res = _run(rule, sigs)
    total_alerts = len(res.fired)
    first = int(res.fired[0].trigger.sid.split(":")[1]) if res.fired else n
    return {
        "rule_id": rule.id,
        "signals": n,
        "alerts": total_alerts,
        "suppressed": sum(f.suppressed_count for f in res.fired),
        "expected_suppressed": n - first - 1,
    }


def run_all(ruleset: RuleSet | None = None, config: Any = None) -> dict[str, Any]:
    if ruleset is None:
        from supervisor.config import REPO_ROOT

        ruleset = load_rules(config or REPO_ROOT / "config" / "alerts.yaml")
    rows, sweeps, storms = [], [], []
    for rid in NINE:
        rule = ruleset.get(rid)
        if rule is None:
            rows.append({"rule_id": rid, "missing": True})
            continue
        rows.append(drill_rule(rule))
        sw = sweep_rate(rule)
        if sw:
            sweeps.append(sw)
        storms.append(storm(rule))
    ok = all(
        not r.get("missing")
        and r["fires"]
        and r["quiet"]
        and r["suppressed"]
        and r["siem_correlation"]
        for r in rows
    )
    ok = ok and all(s["fired_above"] == SWEEP and s["fired_below"] == 0 for s in sweeps)
    ok = ok and all(
        s["alerts"] == 1 and s["suppressed"] == s["expected_suppressed"] for s in storms
    )
    return {"drills": rows, "sweeps": sweeps, "storms": storms, "go": ok}


def render(result: dict[str, Any]) -> list[str]:
    lines = ["alert drills (WP39; thresholds ILLUSTRATIVE; synthetic signals, fixed seed)"]
    for r in result["drills"]:
        if r.get("missing"):
            lines.append(f"  [FAIL] {r['rule_id']}: rule missing from the config")
            continue
        flags = ", ".join(
            f"{k}={'ok' if r[k] else 'FAIL'}"
            for k in ("fires", "quiet", "suppressed", "siem_correlation")
        )
        lines.append(f"  {r['rule_id']:<26} {flags}")
    for s in result["sweeps"]:
        lines.append(
            f"  {s['rule_id']:<26} rate {s['min_bp']}bp: fired above "
            f"{s['fired_above']}/{s['scenarios_per_side']}"
            f" ({s['fired_above_bp']}bp {s['fired_above_ci_bp']}), quiet below "
            f"{s['scenarios_per_side'] - s['fired_below']}/{s['scenarios_per_side']}"
            f" ({s['quiet_below_bp']}bp {s['quiet_below_ci_bp']})"
        )
    for s in result["storms"]:
        lines.append(
            f"  {s['rule_id']:<26} storm {s['signals']} signals -> {s['alerts']} alert, "
            f"{s['suppressed']} suppressed"
        )
    lines.append("[OK] drills GO" if result["go"] else "[FAIL] drills NO-GO")
    return lines

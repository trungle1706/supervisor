"""The rule engine: a pure function from (rules, signals, state) to alerts (WP21, ADR D15).

Deterministic: signals are processed in ``(ts, kind, sid)`` order, counters are per
``(rule, group)``, time comes only from signal timestamps (never the wall clock), ids are
SHA-256 of ``dedupe_key | ts | sid``. The same input gives the same alerts on every run, on
every machine.

Window: a rule fires on a signal when the number of matching signals of its group in
``(ts - window_s, ts]`` reaches ``threshold``. ``window_s = 0`` counts only the signal itself.

Dedupe: the dedupe key is ``<rule id>:<group>``. After a fire at time ``t`` the next
candidates with ``ts - t < dedupe_s`` are *suppressed*: no new alert, the open alert's
``suppressed_count`` goes up. The first candidate at or after ``t + dedupe_s`` fires again.
``last_fired`` (from the ``alert`` table) carries this across runs.

Replay safety: with a ``cursor`` the engine still reads older signals to fill the windows, but
only signals after the cursor can fire or be counted as suppressed, so every signal is judged
once.

Policy suppression: a ``suppressions`` entry (rule, agent, until) drops a candidate and counts
it in ``policy_suppressed``; nothing is stored.
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field
from datetime import datetime, timedelta

from supervisor.alerts.rules import Rule, RuleSet
from supervisor.alerts.signals import Signal, sorted_signals
from supervisor.core.canonical import format_ts, sha256_hex

REF_LIMIT = 8  # signal ids kept on an alert as evidence refs


@dataclass
class FiredAlert:
    alert_id: str
    rule: Rule
    group_value: str
    agent_id: str | None
    ts: datetime
    first_ts: datetime
    last_ts: datetime
    window_count: int
    trigger: Signal
    refs: list[str]
    suppressed_count: int = 0

    @property
    def dedupe_key(self) -> str:
        return f"{self.rule.id}:{self.group_value}"


@dataclass
class EvalResult:
    fired: list[FiredAlert] = field(default_factory=list)
    # dedupe_key -> (count, last suppressed ts) for alerts that were raised in an EARLIER run
    suppressed_existing: dict[str, tuple[int, datetime]] = field(default_factory=dict)
    policy_suppressed: int = 0
    judged: int = 0  # new signals that were looked at
    cursor: tuple[datetime, str] | None = None  # the newest (ts, sid) judged


def dedupe_key(rule_id: str, group: str) -> str:
    return f"{rule_id}:{group}"


def alert_id_for(key: str, ts: datetime, sid: str) -> str:
    return sha256_hex(f"{key}|{format_ts(ts)}|{sid}")[:32]


def evaluate(
    ruleset: RuleSet,
    signals: list[Signal],
    *,
    cursor: tuple[datetime, str] | None = None,
    last_fired: dict[str, datetime] | None = None,
    only_rules: set[str] | None = None,
) -> EvalResult:
    """Run the rules over ``signals``. ``last_fired`` maps dedupe key to the time of the
    newest stored alert; it is updated in place (pass a copy to keep yours)."""
    last = last_fired if last_fired is not None else {}
    result = EvalResult()
    windows: dict[tuple[str, str], deque[tuple[datetime, str]]] = {}
    by_source: dict[str, list[Rule]] = {}
    for r in ruleset.rules:
        if only_rules is None or r.id in only_rules:
            by_source.setdefault(r.source, []).append(r)
    open_here: dict[str, FiredAlert] = {}
    for s in sorted_signals(signals):
        is_new = cursor is None or (s.ts, s.sid) > cursor
        if is_new:
            result.judged += 1
            if result.cursor is None or (s.ts, s.sid) > result.cursor:
                result.cursor = (s.ts, s.sid)
        for rule in by_source.get(s.kind, ()):
            if not rule.matches(s.fields):
                continue
            group = rule.group_of(s.fields)
            win = windows.setdefault((rule.id, group), deque())
            win.append((s.ts, s.sid))
            if rule.window_s == 0:
                while len(win) > 1:
                    win.popleft()  # only the signal itself counts
            else:
                horizon = s.ts - timedelta(seconds=rule.window_s)
                while win[0][0] <= horizon:
                    win.popleft()
            if not is_new or len(win) < rule.threshold:
                continue
            if rule.group_by == "agent_id":
                agent = group if group not in ("-", "*") else None
            else:
                agent = s.agent_id
            if ruleset.suppressed(rule.id, agent, s.ts) is not None:
                result.policy_suppressed += 1
                continue
            key = dedupe_key(rule.id, group)
            prev = last.get(key)
            if prev is not None and s.ts - prev < timedelta(seconds=rule.dedupe_s):
                if key in open_here:
                    open_here[key].suppressed_count += 1
                    open_here[key].last_ts = s.ts
                else:
                    n, _ = result.suppressed_existing.get(key, (0, s.ts))
                    result.suppressed_existing[key] = (n + 1, s.ts)
                continue
            alert = FiredAlert(
                alert_id=alert_id_for(key, s.ts, s.sid),
                rule=rule,
                group_value=group,
                agent_id=agent,
                ts=s.ts,
                first_ts=win[0][0],
                last_ts=s.ts,
                window_count=len(win),
                trigger=s,
                refs=[sid for _, sid in list(win)[-REF_LIMIT:]],
            )
            last[key] = s.ts
            open_here[key] = alert
            result.fired.append(alert)
    return result


__all__ = ["EvalResult", "FiredAlert", "alert_id_for", "dedupe_key", "evaluate"]

"""Gateway engine: Tier 0a synchronous decision, Tier 0b asynchronous hook (ADR D02, D03).

Tier 0a, in order:

1. Read the policy (``PolicyProvider``) and the agent state (``AgentStateMachine``).
2. Unknown agent or unknown tool -> block (closed). QUARANTINED and RETIRED -> block everything.
   PAUSED -> block every tool that is not read-only ("agent paused").
3. Evaluate every rule in scope, in a fixed order (pause > block > alert > log,
   then severity, then rule id). Predicates, aggregates and prior-call checks are
   interpreted by hand here (no eval). The first block/pause rule decides; every
   matched rule is recorded. A rule that raises applies its own fail mode.
4. SHADOW: everything is evaluated and recorded, the call is always allowed.
5. A matched ``pause`` rule pauses the agent (principal ``rule:<id>``).

Any other internal error, or no answer within ``timeout_s`` (2 s), applies the
fail mode of the most severe applicable rule; money, credit and PII-export tools
and unknown tools are always closed.

Every decision appends ``verdict`` rows (tier 0), one ``agent_event`` row
(``event_type=gate_decision``; hashed keys only) and one ``gate_decision`` evidence
record. Chain payloads contain no floats (latency in integer microseconds).
"""

from __future__ import annotations

import concurrent.futures as cf
import hashlib
import json
import logging
import math
import threading
import time
import uuid
from collections import Counter, deque
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any

from supervisor.core.args_hmac import args_hmac, as_key, key_id
from supervisor.core.canonical import canonical_json, format_ts
from supervisor.core.ports import Clock, EvidenceSink, StateStore, TableStore
from supervisor.gateway.facts import FactSource
from supervisor.gateway.policy import (
    DEFAULT_FAIL_MODE,
    FACT_PREFIX,
    SEVERITY_RANK,
    Policy,
    PolicyProvider,
    Predicate,
    RuleSpec,
    ToolMatch,
)
from supervisor.gateway.state import AgentStateMachine
from supervisor.gateway.tier0b import Classifier, RegexClassifier

log = logging.getLogger("supervisor.gateway")

HARD_TIMEOUT_S = 2.0
WARM_LIMIT = 50_000
CHECKER_0A = "gate:tier0a"
CHECKER_FAIL = "gate:fail_mode"


class PredicateTypeError(Exception):
    """A rule compares a value of the wrong type (for example a float amount)."""


_MISSING = object()


def _resolve(path: str, args: Mapping[str, Any], ctx: Mapping[str, Any]) -> Any:
    if path.startswith("ctx."):
        cur: Any = ctx
        parts = path[4:].split(".")
    else:
        cur = args
        parts = path.split(".")
    for p in parts:
        if not isinstance(cur, Mapping) or p not in cur:
            return _MISSING
        cur = cur[p]
    return cur


def _is_int(v: Any) -> bool:
    return type(v) is int


def _same(a: Any, b: Any) -> bool:
    return type(a) is type(b) and a == b


def _compare(op: str, value: Any, target: Any, policy: Policy, what: str) -> bool:
    if op == "absent":
        return value is _MISSING or value is None
    if op == "present":
        return value is not _MISSING and value is not None
    if value is _MISSING:
        return False
    if op == "eq":
        return _same(value, target)
    if op == "ne":
        return not _same(value, target)
    if op == "in":
        return any(_same(value, t) for t in target)
    if op == "not_in":
        return not any(_same(value, t) for t in target)
    if op in ("gt", "ge", "lt", "le"):
        if not _is_int(value):
            raise PredicateTypeError(f"{what}: expected an integer, got {type(value).__name__}")
        return {
            "gt": value > target,
            "ge": value >= target,
            "lt": value < target,
            "le": value <= target,
        }[op]
    if op == "matches":
        if not isinstance(value, str):
            raise PredicateTypeError(f"{what}: expected text, got {type(value).__name__}")
        return policy.pattern(target).search(value[:10_000]) is not None
    raise PredicateTypeError(f"unknown op {op}")


def _fact(path: str, args: Mapping[str, Any], facts: FactSource | None) -> Any:
    """``fact.<source>.<field>``: look the record up by argument ``<source>_id``.

    Every gap raises (rule error -> the rule's fail mode): a missing fact never
    lets a money or credit call through."""
    _, source, name = path.split(".")
    if facts is None:
        raise PredicateTypeError(f"{path}: no fact source configured")
    key = args.get(f"{source}_id")
    if not isinstance(key, str | int) or isinstance(key, bool) or not str(key).strip():
        raise PredicateTypeError(f"{path}: argument {source}_id is needed to read the fact")
    if str(key) != str(key).strip():
        raise PredicateTypeError(f"{path}: argument {source}_id has surrounding spaces")
    record = facts.get(source, str(key))  # the exact id the tool will receive
    if record is None:
        raise PredicateTypeError(f"{path}: no {source} record for this call")
    if name not in record:
        raise PredicateTypeError(f"{path}: {source} record has no field {name}")
    value = record[name]
    if isinstance(value, float):
        raise PredicateTypeError(f"{path}: float facts are not allowed")
    return value


def _pred(
    p: Predicate,
    args: Mapping[str, Any],
    ctx: Mapping[str, Any],
    policy: Policy,
    facts: FactSource | None = None,
) -> bool:
    if p.arg.startswith(FACT_PREFIX):
        value = _fact(p.arg, args, facts)
    else:
        value = _resolve(p.arg, args, ctx)
    return _compare(p.op, value, p.value, policy, p.arg)


def tool_matches(m: ToolMatch | None, tool_name: str, policy: Policy) -> bool:
    if m is None:
        return True
    return _compare(m.op, tool_name, m.value, policy, "tool")


def key_hash(name: str, value: Any) -> str:
    """Stable, non-reversible grouping key (raw ids never stored in events or the chain)."""
    if isinstance(value, bool) or not isinstance(value, str | int):
        raise PredicateTypeError(f"{name}: grouping value must be text or an integer")
    text = str(value).strip().casefold()
    if not text:
        raise PredicateTypeError(f"{name}: grouping value is empty")
    data = f"{name}\x1f{text}".encode()
    return hashlib.sha256(data).hexdigest()[:32]


# --------------------------------------------------------------------------- windows


@dataclass(frozen=True)
class _Event:
    ts_us: int
    agent_id: str
    keys: Mapping[str, str]
    amount: int | None


def _epoch_us(ts: datetime) -> int:
    delta = ts - datetime(1970, 1, 1, tzinfo=ts.tzinfo)
    return (delta.days * 86_400 + delta.seconds) * 1_000_000 + delta.microseconds


class WindowStore:
    """In-memory sliding windows of allowed calls, per tool. Rebuilt from agent_event."""

    def __init__(self) -> None:
        self.by_tool: dict[str, deque[_Event]] = {}
        self.warm = False
        self.policy_hash: str | None = None

    def add(self, tool: str, ev: _Event) -> None:
        self.by_tool.setdefault(tool, deque()).append(ev)

    def prune(self, now_us: int, max_window_s: int) -> None:
        horizon = now_us - max_window_s * 1_000_000
        for dq in self.by_tool.values():
            while dq and dq[0].ts_us < horizon:
                dq.popleft()

    def _iter(self, tools: list[str], since_us: int) -> list[_Event]:
        out = []
        for t in tools:
            for ev in reversed(self.by_tool.get(t, ())):
                if ev.ts_us < since_us:
                    break
                out.append(ev)
        return out

    def total(
        self,
        tools: list[str],
        since_us: int,
        agents: set[str] | None,
        key: Mapping[str, str] | None,
        fn: str,
    ) -> int:
        acc = 0
        for ev in self._iter(tools, since_us):
            if agents is not None and ev.agent_id not in agents:
                continue
            if key and any(ev.keys.get(k) != v for k, v in key.items()):
                continue
            if fn == "count":
                acc += 1
            elif ev.amount is not None:
                acc += ev.amount
        return acc

    def exists(
        self, tool: str, since_us: int, agent_id: str | None, match: Mapping[str, str]
    ) -> bool:
        for ev in self._iter([tool], since_us):
            if agent_id is not None and ev.agent_id != agent_id:
                continue
            if all(ev.keys.get(k) == v for k, v in match.items()):
                return True
        return False


# --------------------------------------------------------------------------- metrics


class GateMetrics:
    def __init__(self, keep: int = 10_000) -> None:
        self._lat: deque[int] = deque(maxlen=keep)
        self.counts: Counter[str] = Counter()
        self._lock = threading.Lock()

    def observe(self, latency_us: int, action: str, allow: bool, extra: str | None = None) -> None:
        with self._lock:
            self._lat.append(int(latency_us))
            self.counts["checks"] += 1
            self.counts[f"action_{action}"] += 1
            self.counts["allowed" if allow else "denied"] += 1
            if extra:
                self.counts[extra] += 1

    def bump(self, name: str) -> None:
        with self._lock:
            self.counts[name] += 1

    @staticmethod
    def percentile(sorted_values: list[int], p: int) -> int:
        if not sorted_values:
            return 0
        rank = max(1, math.ceil(p * len(sorted_values) / 100))
        return sorted_values[rank - 1]

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            values = sorted(self._lat)
            counts = dict(sorted(self.counts.items()))
        return {
            "samples": len(values),
            "latency_us": {
                "p50": self.percentile(values, 50),
                "p95": self.percentile(values, 95),
                "p99": self.percentile(values, 99),
                "max": values[-1] if values else 0,
            },
            "counts": counts,
        }


# --------------------------------------------------------------------------- decision


@dataclass
class Match:
    rule: RuleSpec
    action: str
    error: str | None = None


@dataclass
class Decision:
    decision_id: str
    allow: bool
    action: str
    rule_id: str | None
    reason: str
    agent_state: str | None
    policy_hash: str | None
    risk_class: str | None
    matched: list[dict[str, Any]] = field(default_factory=list)
    fail_mode: str | None = None
    paused: bool = False
    latency_us: int = 0  # decision (evaluation) latency, before recording
    total_us: int = 0  # end to end inside the gateway, recording included

    def as_result(self) -> dict[str, Any]:
        return {
            "allow": self.allow,
            "action": self.action,
            "rule_id": self.rule_id,
            "reason": self.reason,
            "latency_ms": (self.total_us or self.latency_us) // 1000,
            "latency_us": self.latency_us,
            "total_us": self.total_us,
            "decision_id": self.decision_id,
            "agent_state": self.agent_state,
            "policy_hash": self.policy_hash,
            "risk_class": self.risk_class,
            "matched_rules": self.matched,
            "fail_mode": self.fail_mode,
            "agent_paused": self.paused,
        }


class _Call:
    def __init__(self) -> None:
        self.lock = threading.Lock()
        self.abandoned = False
        self.decision: Decision | None = None


class Gateway:
    """Implements ``GateHook``. Thread-safe; ``check`` never raises."""

    def __init__(
        self,
        policy: PolicyProvider,
        tables: TableStore,
        state: StateStore,
        evidence: EvidenceSink,
        clock: Clock,
        *,
        states: AgentStateMachine | None = None,
        classifier: Classifier | None = None,
        facts: FactSource | None = None,
        args_hash_key: str | bytes | None = None,
        tier0b_enabled: bool = True,
        timeout_s: float = HARD_TIMEOUT_S,
        env: str = "local",
        state_cache_ttl_s: float = 1.0,
        workers: int = 8,
        require_caller_id: bool = False,
    ) -> None:
        self.policy = policy
        self.tables = tables
        self.evidence = evidence
        self.clock = clock
        self.states = states or AgentStateMachine(
            state, evidence, clock, policy, cache_ttl_s=state_cache_ttl_s
        )
        self.classifier = classifier or RegexClassifier()
        self.facts = facts
        self._args_key = as_key(args_hash_key)  # None -> fixed dev key (key id "dev")
        self.args_key_id = key_id(self._args_key)
        self.tier0b_enabled = tier0b_enabled
        self.timeout_s = timeout_s
        self.env = env
        # ADR D10 (WP7): a handoff call without caller_agent_id fails closed for
        # money / credit / pii_export tools. Off by default (REQUIRE_CALLER_ID).
        self.require_caller_id = require_caller_id
        self.metrics = GateMetrics()
        self.windows = WindowStore()
        self._lock = threading.RLock()
        self._pool = cf.ThreadPoolExecutor(max_workers=workers, thread_name_prefix="gate0a")
        self._bg = cf.ThreadPoolExecutor(max_workers=2, thread_name_prefix="gate0b")
        self._bg_futures: list[cf.Future[None]] = []

    # ------------------------------------------------------------------ public

    def check(
        self,
        agent_id: str,
        agent_version: str,
        tool_name: str,
        args: Mapping[str, Any],
        context: Mapping[str, Any] | None = None,
    ) -> dict[str, Any]:
        t0 = time.perf_counter_ns()
        ctx = dict(context or {})
        args = dict(args or {})
        call = _Call()
        try:
            fut = self._pool.submit(
                self._decide, call, t0, agent_id, agent_version, tool_name, args, ctx
            )
            decision = fut.result(timeout=self.timeout_s)
        except cf.TimeoutError:
            with call.lock:
                if call.decision is None:
                    call.abandoned = True
                committed = call.decision
            if committed is not None:
                # Decided in time; only the recording is slow. Recording continues.
                decision = committed
            else:
                decision = self._fail(
                    t0,
                    agent_id,
                    agent_version,
                    tool_name,
                    args,
                    ctx,
                    TimeoutError(f"no decision within {self.timeout_s:g} s"),
                )
        except Exception as exc:  # noqa: BLE001 - check() must never raise
            decision = self._fail(t0, agent_id, agent_version, tool_name, args, ctx, exc)
        return decision.as_result()

    def drain(self, timeout_s: float = 5.0) -> None:
        """Wait for queued Tier 0b work (tests and shutdown)."""
        with self._lock:
            futures, self._bg_futures = self._bg_futures, []
        cf.wait(futures, timeout=timeout_s)

    def close(self) -> None:
        self.drain()
        self._pool.shutdown(wait=False, cancel_futures=True)
        self._bg.shutdown(wait=False, cancel_futures=True)

    # ------------------------------------------------------------------ 0a

    def _now_us(self) -> tuple[datetime, int]:
        now = self.clock.now()
        return now, _epoch_us(now)

    def _warm(self, policy: Policy) -> None:
        """Rebuild windows from allowed gate_decision events (cold start)."""
        now, now_us = self._now_us()
        horizon = now - timedelta(seconds=policy.max_window_s)
        store = WindowStore()
        tracked = _window_tools(policy)
        rows: list[dict[str, Any]] = []
        for tool in sorted(tracked):
            rows += self.tables.query(
                "agent_event",
                {"event_type": "gate_decision", "status": "allowed", "tool_name": tool},
                order_by=("-ts",),
                limit=WARM_LIMIT,
            )
        rows.sort(key=lambda r: r["ts"], reverse=True)
        for r in reversed(rows):
            if r["ts"] < horizon or r["tool_name"] not in tracked:
                continue
            try:
                keys = json.loads(r["args_masked"] or "{}").get("keys", {})
            except ValueError:
                keys = {}
            store.add(
                r["tool_name"],
                _Event(_epoch_us(r["ts"]), r["agent_id"], dict(keys), r["amount_minor"]),
            )
        store.prune(now_us, policy.max_window_s)
        store.warm = True
        store.policy_hash = policy.policy_hash
        self.windows = store

    def _rule_matches(
        self,
        rule: RuleSpec,
        agent_id: str,
        tool_name: str,
        args: Mapping[str, Any],
        ctx: Mapping[str, Any],
        policy: Policy,
        now_us: int,
    ) -> bool:
        if not tool_matches(rule.when.tool, tool_name, policy):
            return False
        facts = self.facts
        if not all(_pred(p, args, ctx, policy, facts) for p in rule.when.all):
            return False
        if rule.when.any and not any(_pred(p, args, ctx, policy, facts) for p in rule.when.any):
            return False
        agg = rule.aggregate
        if agg is not None:
            since = now_us - agg.window_s * 1_000_000
            if agg.fn == "sum":
                assert agg.field is not None
                current = _resolve(agg.field, args, ctx)
                if current is _MISSING or current is None:
                    return False  # a separate "absent" rule blocks calls without an amount
                if not _is_int(current):
                    raise PredicateTypeError(f"{agg.field}: expected an integer amount")
                if current < 0:
                    raise PredicateTypeError(f"{agg.field}: negative amount")
            else:
                current = 1
            key: dict[str, str] = {}
            agents = None if rule.agent_scope == "*" else set(rule.agent_scope)
            group = list(agg.also_by)
            if agg.group_by == "customer":
                group.insert(0, agg.customer_arg)
            else:
                agents = {agent_id}
            for name in group:
                value = _resolve(name, args, ctx)
                if value is _MISSING or value is None:
                    raise PredicateTypeError(f"{name}: needed to group the limit")
                key[name] = key_hash(name, value)
            total = current + self.windows.total(rule.counted_tools(), since, agents, key, agg.fn)
            return total > agg.limit if agg.op == "gt" else total >= agg.limit
        prior = rule.prior
        if prior is not None:
            match: dict[str, str] = {}
            for name in prior.match_args:
                value = _resolve(name, args, ctx)
                if value is _MISSING or value is None:
                    # Cannot link to an earlier call: treat as a match (both modes), so a
                    # missing id never slips past a money control.
                    return True
                match[name] = key_hash(name, value)
            since = now_us - prior.within_s * 1_000_000
            found = self.windows.exists(
                prior.tool, since, agent_id if prior.same_agent else None, match
            )
            return found if prior.mode == "present" else not found
        return True

    def _decide(
        self,
        call: _Call,
        t0: int,
        agent_id: str,
        agent_version: str,
        tool_name: str,
        args: dict[str, Any],
        ctx: dict[str, Any],
    ) -> Decision:
        with self._lock:
            policy = self.policy.current()
            if not self.windows.warm or self.windows.policy_hash != policy.policy_hash:
                self._warm(policy)  # cold start, or new policy (tracked keys may differ)
            state = self.states.get_state(agent_id, policy)
            risk = policy.risk_class(tool_name)
            now, now_us = self._now_us()
            self.windows.prune(now_us, policy.max_window_s)
            matches: list[Match] = []
            builtin: tuple[str, str] | None = None
            if state is None:
                builtin = ("GATE-UNKNOWN-AGENT", f"unknown agent {agent_id}: fail closed")
            elif state == "QUARANTINED":
                builtin = ("GATE-QUARANTINED", "agent quarantined")
            elif state == "RETIRED":
                builtin = ("GATE-RETIRED", "agent retired")
            elif state == "PAUSED" and risk != "read_only":
                builtin = ("GATE-PAUSED", "agent paused")
            elif risk is None and state != "SHADOW":
                builtin = ("GATE-UNKNOWN-TOOL", f"unknown tool {tool_name}: fail closed")
            elif (
                self.require_caller_id
                and state != "SHADOW"
                and DEFAULT_FAIL_MODE.get(risk or "") == "closed"
                and _is_handoff(ctx)
                and not _caller(ctx)
            ):
                builtin = (
                    "GATE-NO-CALLER",
                    f"handoff to {agent_id} without caller_agent_id: fail closed (ADR D10)",
                )
            else:
                for rule in policy.rules_for(agent_id):
                    try:
                        if self._rule_matches(rule, agent_id, tool_name, args, ctx, policy, now_us):
                            matches.append(Match(rule, rule.action))
                    except Exception as exc:  # noqa: BLE001 - per-rule fail mode
                        err = f"{type(exc).__name__}: {exc}"[:300]
                        act = "block" if rule.effective_fail_mode == "closed" else "alert"
                        matches.append(Match(rule, act, error=err))
                matches.sort(key=lambda m: _ACTION_ORDER[m.action])

            decision_id = uuid.uuid4().hex
            shadow = state == "SHADOW"
            decisive = next((m for m in matches if m.action in ("block", "pause")), None)
            fail_mode = None
            if builtin is not None:
                d = Decision(
                    decision_id,
                    False,
                    "block",
                    builtin[0],
                    builtin[1],
                    state,
                    policy.policy_hash,
                    risk,
                )
            elif decisive is not None and not shadow:
                reason = (
                    f"{decisive.rule.id}: {decisive.rule.description}"
                    if decisive.error is None
                    else f"{decisive.rule.id}: rule error, fail closed ({decisive.error})"
                )
                if decisive.error is not None:
                    fail_mode = "closed"
                d = Decision(
                    decision_id,
                    False,
                    decisive.action,
                    decisive.rule.id,
                    reason,
                    state,
                    policy.policy_hash,
                    risk,
                )
            else:
                top = matches[0] if matches else None
                if shadow and decisive is not None:
                    action, rid = "log", decisive.rule.id
                    reason = f"shadow: would {decisive.action} by {decisive.rule.id}"
                elif shadow and risk is None:
                    action, rid, reason = "log", "GATE-UNKNOWN-TOOL", "shadow: would block"
                elif top is not None:
                    action, rid = top.action, top.rule.id
                    reason = f"{top.rule.id}: {top.rule.description}"
                    if top.error is not None:
                        fail_mode = "open"
                        reason = f"{top.rule.id}: rule error, fail open ({top.error})"
                else:
                    action, rid, reason = "allow", None, "allowed"
                d = Decision(
                    decision_id, True, action, rid, reason, state, policy.policy_hash, risk
                )
            d.fail_mode = fail_mode
            d.matched = [
                {
                    "rule_id": m.rule.id,
                    "version": m.rule.version,
                    "action": m.action,
                    "severity": m.rule.severity,
                    "error": m.error is not None,
                }
                for m in matches
            ]
            with call.lock:
                if call.abandoned:
                    return d  # the caller already applied the fail mode and recorded it
                call.decision = d
            if d.allow and tool_name in _window_tools(policy):
                self._remember(policy, now_us, agent_id, tool_name, args, ctx)
            pause_rule = next((m for m in matches if m.action == "pause"), None)
            if pause_rule is not None and not shadow and builtin is None:
                self.states.pause(
                    agent_id,
                    f"rule:{pause_rule.rule.id}",
                    f"{pause_rule.rule.id}: {pause_rule.rule.description}",
                    auth_method="local_system",
                    actor_kind="system",
                )
                d.paused = True
            d.latency_us = (time.perf_counter_ns() - t0) // 1000
            self._record(d, now, agent_id, agent_version, tool_name, args, ctx, matches, shadow)
        d.total_us = (time.perf_counter_ns() - t0) // 1000
        self.metrics.observe(
            d.total_us,
            d.action,
            d.allow,
            "shadow" if shadow else (f"fail_{d.fail_mode}" if d.fail_mode else None),
        )
        self._tier0b(d, agent_id, tool_name, args, risk, ctx)
        return d

    def _event_keys(
        self, policy: Policy, tool_name: str, args: Mapping[str, Any], ctx: Mapping[str, Any]
    ) -> dict[str, str]:
        keys: dict[str, str] = {}
        names = set(policy.tracked_keys().get(tool_name, ())) | DEFAULT_KEYS
        for name in sorted(names):
            value = _resolve(name, args, ctx)
            if value is _MISSING or value is None:
                continue
            try:
                keys[name] = key_hash(name, value)
            except PredicateTypeError:
                continue
        return keys

    def _remember(
        self,
        policy: Policy,
        now_us: int,
        agent_id: str,
        tool_name: str,
        args: Mapping[str, Any],
        ctx: Mapping[str, Any],
    ) -> None:
        amount = args.get("amount_minor")
        self.windows.add(
            tool_name,
            _Event(
                now_us,
                agent_id,
                self._event_keys(policy, tool_name, args, ctx),
                amount if _is_int(amount) and amount >= 0 else None,
            ),
        )

    def _record(
        self,
        d: Decision,
        now: datetime,
        agent_id: str,
        agent_version: str,
        tool_name: str,
        args: Mapping[str, Any],
        ctx: Mapping[str, Any],
        matches: list[Match],
        shadow: bool,
    ) -> None:
        trace_id = ctx.get("trace_id") if isinstance(ctx.get("trace_id"), str) else None
        latency_ms = d.latency_us // 1000
        rows: list[dict[str, Any]] = []
        base = {
            "ts": now,
            "trace_id": trace_id,
            "event_id": d.decision_id,
            "agent_id": agent_id,
            "tier": 0,
            "model_id": None,
            "model_family": None,
            "is_mock": False,
            "advisory": False,
            "score": None,
            "latency_ms": latency_ms,
            "policy_hash": d.policy_hash,
        }
        if matches:
            for m in matches:
                if shadow:
                    action, label = "log", f"shadow_would_{m.action}"
                else:
                    action, label = m.action, ("rule_error" if m.error else "matched")
                rows.append(
                    {
                        **base,
                        "verdict_id": uuid.uuid4().hex,
                        "checker_id": CHECKER_0A,
                        "label": label,
                        "action": action,
                        "rule_id": m.rule.id,
                        "rationale_masked": m.rule.description,
                    }
                )
        else:
            rows.append(
                {
                    **base,
                    "verdict_id": uuid.uuid4().hex,
                    "checker_id": CHECKER_0A,
                    "label": "shadow_unknown_tool" if shadow and d.rule_id else d.action,
                    "action": d.action,
                    "rule_id": d.rule_id,
                    "rationale_masked": d.reason[:500],
                }
            )
        self.tables.append("verdict", rows)
        self._append_event(d, now, agent_id, agent_version, tool_name, args, ctx)
        self.evidence.record(
            "gate_decision",
            d.decision_id,
            self._payload(d, now, agent_id, agent_version, tool_name, args, ctx),
        )

    def _append_event(
        self,
        d: Decision,
        now: datetime,
        agent_id: str,
        agent_version: str,
        tool_name: str,
        args: Mapping[str, Any],
        ctx: Mapping[str, Any],
    ) -> None:
        policy = self.policy.last_known()
        keys = self._event_keys(policy, tool_name, args, ctx) if policy else {}
        amount = args.get("amount_minor")
        currency = args.get("currency")
        caller = ctx.get("caller_agent_id")
        self.tables.append(
            "agent_event",
            [
                {
                    "event_id": d.decision_id,
                    "ts": now,
                    "trace_id": str(ctx.get("trace_id") or d.decision_id),
                    "span_id": str(ctx.get("span_id") or d.decision_id[:16]),
                    "parent_span_id": None,
                    "agent_id": agent_id,
                    "agent_version": agent_version,
                    "caller_agent_id": caller if isinstance(caller, str) else None,
                    "event_type": "gate_decision",
                    "tool_name": tool_name,
                    "args_hash": args_hmac(args, self._args_key),  # keyed, not plain SHA-256
                    "args_masked": canonical_json({"keys": keys}),
                    "amount_minor": amount if _is_int(amount) else None,
                    "currency": currency
                    if isinstance(currency, str) and len(currency) == 3 and currency.isupper()
                    else None,
                    "status": "allowed" if d.allow else "denied",
                    "latency_ms": d.latency_us // 1000,
                    "env": self.env,
                    "classification": d.action,
                    "source": "proxy",
                    "capture_level": "digest",
                }
            ],
        )

    def _payload(
        self,
        d: Decision,
        now: datetime,
        agent_id: str,
        agent_version: str,
        tool_name: str,
        args: Mapping[str, Any],
        ctx: Mapping[str, Any],
    ) -> dict[str, Any]:
        amount = args.get("amount_minor")
        trace_id = ctx.get("trace_id")
        caller = ctx.get("caller_agent_id")
        return {
            "decision_id": d.decision_id,
            "ts": format_ts(now),
            "agent_id": agent_id,
            "agent_version": str(agent_version),
            "tool_name": tool_name,
            "risk_class": d.risk_class,
            "agent_state": d.agent_state,
            "allow": d.allow,
            "action": d.action,
            "rule_id": d.rule_id,
            "reason": d.reason[:500],
            "matched": d.matched,
            "policy_hash": d.policy_hash,
            "args_hmac": args_hmac(args, self._args_key),
            "args_hmac_key_id": self.args_key_id,
            "amount_minor": amount if _is_int(amount) else None,
            "latency_us": int(d.latency_us),
            "fail_mode": d.fail_mode,
            "agent_paused": d.paused,
            "trace_id": trace_id if isinstance(trace_id, str) else None,
            # ADR D10: who handed the work to this agent (None for a direct call).
            "caller_agent_id": caller if isinstance(caller, str) else None,
            "tier": 0,
        }

    # ------------------------------------------------------------------ fail mode

    def fail_mode_for(self, agent_id: str, tool_name: str) -> tuple[str, str | None]:
        """(mode, rule_id) to apply when the gateway cannot decide."""
        policy = self.policy.last_known()
        if policy is None:
            return "closed", None
        risk = policy.risk_class(tool_name)
        if risk is None or agent_id not in policy.doc.agents:
            return "closed", None
        if self.states.last_known_state(agent_id) in ("QUARANTINED", "PAUSED", "RETIRED") and (
            risk != "read_only"
            or self.states.last_known_state(agent_id) in ("QUARANTINED", "RETIRED")
        ):
            return "closed", None
        applicable = [
            r for r in policy.rules_for(agent_id) if _tool_maybe(r.when.tool, tool_name, policy)
        ]
        mode = DEFAULT_FAIL_MODE[risk]
        rule_id = None
        if applicable:
            worst = max(
                applicable,
                key=lambda r: (
                    SEVERITY_RANK[r.severity],
                    r.effective_fail_mode == "closed",
                    r.id,
                ),
            )
            rule_id = worst.id
            if worst.effective_fail_mode == "closed":
                mode = "closed"
        return mode, rule_id

    def _fail(
        self,
        t0: int,
        agent_id: str,
        agent_version: str,
        tool_name: str,
        args: Mapping[str, Any],
        ctx: Mapping[str, Any],
        exc: BaseException,
    ) -> Decision:
        try:
            mode, rule_id = self.fail_mode_for(agent_id, tool_name)
        except Exception:  # noqa: BLE001
            mode, rule_id = "closed", None
        policy = self.policy.last_known()
        risk = policy.risk_class(tool_name) if policy else None
        what = f"{type(exc).__name__}"
        if mode == "closed":
            d = Decision(
                uuid.uuid4().hex,
                False,
                "block",
                rule_id or "GATE-FAIL-CLOSED",
                f"gateway cannot decide ({what}): fail closed",
                None,
                policy.policy_hash if policy else None,
                risk,
            )
        else:
            d = Decision(
                uuid.uuid4().hex,
                True,
                "alert",
                rule_id or "GATE-FAIL-OPEN",
                f"gateway cannot decide ({what}): fail open, alert raised",
                None,
                policy.policy_hash if policy else None,
                risk,
            )
        d.fail_mode = mode
        d.latency_us = (time.perf_counter_ns() - t0) // 1000
        log.warning("gate fail %s for %s/%s: %r", mode, agent_id, tool_name, exc)
        try:
            now = self.clock.now()
            self.tables.append(
                "verdict",
                [
                    {
                        "verdict_id": uuid.uuid4().hex,
                        "ts": now,
                        "trace_id": ctx.get("trace_id")
                        if isinstance(ctx.get("trace_id"), str)
                        else None,
                        "event_id": d.decision_id,
                        "agent_id": agent_id,
                        "tier": 0,
                        "checker_id": CHECKER_FAIL,
                        "is_mock": False,
                        "advisory": False,
                        "score": None,
                        "label": f"fail_{mode}",
                        "action": d.action,
                        "latency_ms": d.latency_us // 1000,
                        "rule_id": d.rule_id,
                        "policy_hash": d.policy_hash,
                        "rationale_masked": d.reason,
                    }
                ],
            )
        except Exception:  # noqa: BLE001 - the store may be the thing that failed
            self.metrics.bump("record_failed")
        try:
            self.evidence.record(
                "gate_decision",
                d.decision_id,
                self._payload(d, self.clock.now(), agent_id, agent_version, tool_name, args, ctx),
            )
        except Exception:  # noqa: BLE001
            self.metrics.bump("evidence_failed")
        d.total_us = (time.perf_counter_ns() - t0) // 1000
        self.metrics.observe(d.total_us, d.action, d.allow, f"fail_{mode}")
        return d

    # ------------------------------------------------------------------ 0b

    def _tier0b(
        self,
        d: Decision,
        agent_id: str,
        tool_name: str,
        args: Mapping[str, Any],
        risk: str | None,
        ctx: Mapping[str, Any],
    ) -> None:
        if not self.tier0b_enabled or risk == "read_only":
            return
        fut = self._bg.submit(
            self._run_tier0b,
            d.decision_id,
            d.policy_hash,
            agent_id,
            tool_name,
            dict(args),
            ctx.get("trace_id"),
        )
        with self._lock:
            self._bg_futures = [f for f in self._bg_futures if not f.done()]
            self._bg_futures.append(fut)

    def _run_tier0b(
        self,
        decision_id: str,
        policy_hash: str | None,
        agent_id: str,
        tool_name: str,
        args: Mapping[str, Any],
        trace_id: Any,
    ) -> None:
        t0 = time.perf_counter_ns()
        try:
            findings = self.classifier.classify(tool_name, args)
            if not findings:
                return
            now = self.clock.now()
            latency_ms = (time.perf_counter_ns() - t0) // 1_000_000
            checker = f"gate:tier0b:{getattr(self.classifier, 'name', 'classifier')}"
            self.tables.append(
                "verdict",
                [
                    {
                        "verdict_id": uuid.uuid4().hex,
                        "ts": now,
                        "trace_id": trace_id if isinstance(trace_id, str) else None,
                        "event_id": decision_id,
                        "agent_id": agent_id,
                        "tier": 0,
                        "checker_id": checker,
                        "is_mock": False,
                        "advisory": True,
                        "score": None,
                        "label": f.kind,
                        "action": "alert",
                        "latency_ms": latency_ms,
                        "rule_id": None,
                        "policy_hash": policy_hash,
                        "rationale_masked": f"{f.kind} x{f.count} in args of {tool_name}",
                    }
                    for f in findings
                ],
            )
            self.evidence.record(
                "gate_tier0b",
                decision_id,
                {
                    "decision_id": decision_id,
                    "agent_id": agent_id,
                    "tool_name": tool_name,
                    "checker_id": checker,
                    "action": "alert",
                    "findings": [{"kind": f.kind, "count": f.count} for f in findings],
                    "ts": format_ts(now),
                },
            )
            self.metrics.bump("tier0b_alerts")
        except Exception:  # noqa: BLE001 - 0b never affects the call
            log.exception("tier 0b failed")
            self.metrics.bump("tier0b_errors")


# Grouping ids always hashed into gate events, so a new aggregate rule has history.
DEFAULT_KEYS = frozenset({"customer_id", "payee_id", "application_id", "account_id"})


def _is_handoff(ctx: Mapping[str, Any]) -> bool:
    """The call was handed over by another agent (context ``handoff: true``, ADR D10)."""
    return ctx.get("handoff") is True or ctx.get("via") == "handoff"


def _caller(ctx: Mapping[str, Any]) -> str | None:
    caller = ctx.get("caller_agent_id")
    return caller if isinstance(caller, str) and caller.strip() else None


def _window_tools(policy: Policy) -> set[str]:
    """Tools whose allowed calls feed the windows: tracked ones plus every non-read-only tool."""
    tools = set(policy.tracked_keys())
    tools |= {t for t, rc in policy.doc.tools.items() if rc != "read_only"}
    return tools


_ACTION_ORDER = {"pause": 0, "block": 1, "alert": 2, "log": 3}


def _tool_maybe(m: ToolMatch | None, tool_name: str, policy: Policy) -> bool:
    try:
        return tool_matches(m, tool_name, policy)
    except Exception:  # noqa: BLE001
        return True

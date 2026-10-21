"""Gate side of the session monitor (WP27, ADR D29, docs/session-monitor.md).

``SessionGate`` is built only when ``SESSION_MONITOR_ENABLED=1``. With it off the gateway does not
call into this module and its answer and records are exactly as before.

Per gate call (input direction only):

* ``prepare`` runs BEFORE the gate lock (like the detector pass): session identity from the
  context (``session_id``, ``consumer_id``, ``turn_text``), the features of the turn (text is
  read in memory and dropped; only flags and a keyed sketch survive), and the lookup of an
  active session pause.
* ``_evaluate`` turns an active pause plus a tool class in the pause scope into the built-in
  block ``GATE-SESSION-PAUSE``. That is a deterministic rule (R1): the score and the
  thresholds are integers from the policy.
* ``observe`` runs AFTER the decision, outside the gate lock: it adds the turn to the session
  window, assesses it, and applies the case rule and the pause rule through
  ``SessionActions``. It never raises and never changes the decision that was just made.

Everything stored is a hash, a flag or an integer (R2). Pauses apply from the NEXT call.
"""

from __future__ import annotations

import logging
import threading
import time
from collections import OrderedDict
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from supervisor.monitors.common import MonitorContext
from supervisor.monitors.session import (
    Features,
    SessionConfig,
    SessionEngine,
    Turn,
    daily_cap_minor,
    extract_flags,
    identify,
    lookback_s,
    resolve_config,
    session_key,
    timeline,
    with_args,
)
from supervisor.monitors.session_actions import SessionActions

log = logging.getLogger("supervisor.gateway.session")

PAUSE_RULE = "GATE-SESSION-PAUSE"
RARE_SHARE_BP = 200  # a tool with a drift-baseline share below this is a rare tool
REFRESH_S = 2.0  # how often the gate re-reads active pauses written by another process
BASELINE_TTL_S = 60.0
FORGET_EVERY_S = 300.0
MAX_PENDING = 5000  # late Tier 0b codes parked for turns not stored yet (oldest dropped first)
PII_CACHE = 4096  # client session ids already checked by the masker


@dataclass
class SessionCall:
    """Per-call session context, carried on the Decision (``Decision.sess``)."""

    session_id: str
    source: str  # client | derived
    consumer: str | None
    features: Features = field(default_factory=Features)
    pause_id: str | None = None  # an active pause that covers this call's tool class
    day: str = ""
    text: str | None = None  # the turn text, kept in memory until finalize() and then dropped
    final: bool = False


def epoch_ms(ts: datetime) -> int:
    return int(ts.timestamp() * 1000)


def finding_codes(det: Any, *, recorded: bool = False) -> list[str]:
    """Codes of the fired detector findings that count for the session. A mock finding (the
    mock judge) is a test value, not evidence about the conversation: it is left out.

    WP41 (D24, D25): only findings of a detector that is deterministic or has the MRM status GO
    count (``det.weigh_slugs``); with ``recorded=True`` the others are returned instead, to be
    kept on the turn with weight 0 (a report-only classifier must not fill the signal)."""
    weigh = getattr(det, "weigh_slugs", None)
    return [
        str(f.code)
        for f in getattr(det, "findings", ()) or ()
        if not getattr(f, "is_mock", False)
        and (weigh is None or (f.detector_slug in weigh) != recorded)
    ]


class BaselineTools:
    """Drift-baseline tool shares per agent (``policy_baseline`` rows of the drift monitor).

    Used for the "topic drift marker" signal: a tool the baseline calls rare is a marker."""

    def __init__(self, state: Any) -> None:
        self.state = state
        self._cache: dict[str, tuple[float, dict[str, int]]] = {}

    def shares(self, agent_id: str) -> dict[str, int]:
        now = time.monotonic()
        hit = self._cache.get(agent_id)
        if hit is not None and now - hit[0] < BASELINE_TTL_S:
            return hit[1]
        out: dict[str, int] = {}
        try:
            for row in self.state.query("policy_baseline", {"agent_id": agent_id}):
                metric = str(row["metric"])
                if metric.startswith("tool_share_bp:"):
                    tool = metric.split(":", 1)[1]
                    out[tool] = max(out.get(tool, 0), int(row["center"]))
        except Exception:  # noqa: BLE001 - no baseline means no marker, never an error
            out = {}
        self._cache[agent_id] = (now, out)
        return out

    def is_rare(self, agent_id: str, tool: str) -> bool:
        shares = self.shares(agent_id)
        return bool(shares) and shares.get(tool, 0) < RARE_SHARE_BP


class SessionGate:
    def __init__(
        self,
        settings: Any,
        ctx: MonitorContext,
        *,
        key: str | bytes | None = None,
        resume_window_s: int = 900,
        role_of: Any = None,
    ) -> None:
        self.settings = settings
        self.ctx = ctx
        self.key = session_key(key)
        self.engine = SessionEngine()
        self.actions = SessionActions(ctx, resume_window_s=resume_window_s, role_of=role_of)
        self.baselines = BaselineTools(ctx.state)
        self._lock = threading.Lock()
        self._act_lock = threading.Lock()  # one case / pause decision at a time
        self._warmed = False
        self._reloading = False
        self._policy: Any = None
        self._pending: OrderedDict[str, list[str]] = OrderedDict()
        self._local: dict[tuple[str, str], float] = {}  # pauses set here: monotonic set time
        self._pii_seen: OrderedDict[str, bool] = OrderedDict()
        self._masker: Any = None
        self.sync_reload = False
        self._cfg: dict[tuple[str, str], tuple[SessionConfig, int | None]] = {}
        self._pauses: dict[tuple[str, str], tuple[str, int, tuple[str, ...]]] = {}
        self._pause_read = 0.0
        self._forgot = time.monotonic()
        self.stats = {"observed": 0, "cases": 0, "pauses": 0, "errors": 0}

    # ------------------------------------------------------------------ config

    def config_for(self, policy: Any, agent_id: str) -> tuple[SessionConfig, int | None]:
        ck = (getattr(policy, "policy_hash", ""), agent_id)
        hit = self._cfg.get(ck)
        if hit is None:
            manifest = policy.doc.agents.get(agent_id)
            mons = manifest.monitors if manifest is not None else None
            binding = mons.session if mons is not None else None
            hit = (resolve_config(self.settings, binding), daily_cap_minor(policy, agent_id))
            if len(self._cfg) > 512:
                self._cfg.clear()
            self._cfg[ck] = hit
        return hit

    # ------------------------------------------------------------------ before the lock

    def prepare(
        self,
        policy: Any,
        now: datetime,
        agent_id: str,
        tool_name: str,
        args: Mapping[str, Any],
        ctx: Mapping[str, Any],
        *,
        dry: bool = False,
    ) -> SessionCall | None:
        """Session identity, turn features and the pause lookup. None when the agent's policy
        switches the monitor off. Never raises."""
        try:
            cfg, _ = self.config_for(policy, agent_id)
            if not cfg.enabled:
                return None
            sid, source, consumer = identify(
                agent_id, ctx, now.strftime("%Y-%m-%d"), self.key, is_pii=self.is_pii
            )
            if sid is None:  # no session id and no consumer id: nothing joins the turns
                return None
            call = SessionCall(sid, source, consumer, day=now.strftime("%Y-%m-%d"))
            risk = policy.risk_class(tool_name)
            if not dry:
                text = ctx.get("turn_text")
                call.text = text if isinstance(text, str) else None
                call.features = extract_flags(
                    call.text, risk=risk, rare=self.baselines.is_rare(agent_id, tool_name)
                )
            call.pause_id = self.paused(agent_id, sid, risk, epoch_ms(now))
            return call
        except Exception as exc:  # noqa: BLE001 - the monitor must never break the gate
            log.warning("session prepare failed: %s", type(exc).__name__)
            self.stats["errors"] += 1
            return None

    def is_pii(self, session_id: str) -> bool:
        """True when the VN masker would change the id (a phone, CCCD or account number used as
        a conversation id): such an id is not stored. Cached; never raises."""
        hit = self._pii_seen.get(session_id)
        if hit is not None:
            return hit
        try:
            if self._masker is None:
                from supervisor.adapters.masking.vn_regex import VnRegexMasker

                self._masker = VnRegexMasker(self.key)
            hit = self._masker.mask(session_id) != session_id
        except Exception:  # noqa: BLE001 - a masker problem: do not trust the id
            hit = True
        with self._lock:
            self._pii_seen[session_id] = hit
            while len(self._pii_seen) > PII_CACHE:
                self._pii_seen.popitem(last=False)
        return hit

    def finalize(self, call: SessionCall, args: Mapping[str, Any], risk: str | None) -> None:
        """Compute the sketch and the identifier tokens from ``args`` (the masked arguments when
        the dlp transform produced some) and drop the turn text. Idempotent."""
        if call.final:
            return
        call.final = True
        try:
            call.features = with_args(call.features, call.text, args, risk=risk, key=self.key)
        finally:
            call.text = None

    # ------------------------------------------------------------------ pause lookup

    def _reload(self, now_ms: int) -> None:
        """Re-read active pauses at most every REFRESH_S, in a background thread so that a slow
        store (Delta over REST) never delays a gate call. Pauses this process sets are added
        to the map at once; ``sync_reload`` (tests) reads in the calling thread."""
        mono = time.monotonic()
        if mono - self._pause_read < REFRESH_S or self._reloading:
            return
        self._pause_read = mono
        if self.sync_reload:
            self._reload_now(now_ms)
            return
        self._reloading = True

        def work() -> None:
            try:
                self._reload_now(now_ms)
            except Exception:  # noqa: BLE001 - a failed read keeps the last known pauses
                log.exception("session pause reload failed")
            finally:
                self._reloading = False

        threading.Thread(target=work, name="session-pause-reload", daemon=True).start()

    def _reload_now(self, now_ms: int) -> None:
        started = time.monotonic()
        fresh: dict[tuple[str, str], tuple[str, int, tuple[str, ...]]] = {}
        stale = False
        for row in self.actions.active_pauses():
            exp = epoch_ms(row["expires_at"])
            if exp <= now_ms:
                stale = True
            else:
                scope = tuple(s for s in str(row["scope"]).split(",") if s)
                fresh[(row["agent_id"], row["session_id"])] = (str(row["control_id"]), exp, scope)
        with self._lock:
            # a pause this process set while the read was in flight is not in ``fresh`` yet:
            # keep it, or the next calls of that session would pass until the next reload
            for k, v in self._pauses.items():
                if k not in fresh and self._local.get(k, -1.0) >= started and v[1] > now_ms:
                    fresh[k] = v
            self._pauses = fresh
            for k in [k for k, t in self._local.items() if t < started - 10 * REFRESH_S]:
                del self._local[k]
        if stale:  # cool-down ran out: close the rows and record it on the chain
            try:
                self.actions.expire()
            except Exception:  # noqa: BLE001
                log.exception("session pause expiry failed")

    def paused(self, agent_id: str, session_id: str, risk: str | None, now_ms: int) -> str | None:
        """The id of an active session pause that covers ``risk``, else None."""
        self._reload(now_ms)
        hit = self._pauses.get((agent_id, session_id))
        if hit is None:
            return None
        control_id, expires_ms, scope = hit
        if expires_ms <= now_ms:
            with self._lock:
                self._pauses.pop((agent_id, session_id), None)
            try:
                self.actions.expire()
            except Exception:  # noqa: BLE001
                log.exception("session pause expiry failed")
            return None
        return control_id if risk in scope else None

    def drop_pauses(self, agent_id: str | None = None) -> None:
        """Forget cached pauses (after a resume); the next call re-reads the store."""
        with self._lock:
            if agent_id is None:
                self._pauses.clear()
                self._local.clear()
            else:
                for k in [k for k in self._pauses if k[0] == agent_id]:
                    del self._pauses[k]
                for k in [k for k in self._local if k[0] == agent_id]:
                    del self._local[k]
        self._pause_read = 0.0

    # ------------------------------------------------------------------ after the decision

    def observe(
        self,
        policy: Any,
        now: datetime,
        d: Any,
        agent_id: str,
        tool_name: str,
        args: Mapping[str, Any],
        call: SessionCall,
    ) -> None:
        """Add the turn, assess the window, act on the rules. Never raises."""
        try:
            cfg, cap = self.config_for(policy, agent_id)
            if not self._warmed:
                self._warm(policy, now, exclude=d.decision_id)
            risk_class = policy.risk_class(tool_name)
            self.finalize(
                call, getattr(d, "masked_args", None) or d.transformed_args or args, risk_class
            )
            amount = args.get("amount_minor")
            det = getattr(d, "det", None)
            codes = tuple(
                [f"d:{c}" for c in finding_codes(det)]
                + [f"r:{c}" for c in finding_codes(det, recorded=True)]
            )
            now_ms = epoch_ms(now)
            turn = Turn(
                event_id=d.decision_id,
                ts_ms=now_ms,
                agent_id=agent_id,
                tool=tool_name,
                risk=policy.risk_class(tool_name) or "unknown",
                refused=not d.allow,
                amount_minor=amount
                if isinstance(amount, int) and not isinstance(amount, bool)
                else None,
                codes=codes,
                cues=call.features.cues,
                expand=call.features.expand,
                rare=call.features.rare,
                sig=call.features.sig,
                consumer=call.consumer,
                rule_id=d.rule_id,
                assert_=call.features.assert_,
                recall=call.features.recall,
                toks=call.features.toks,
                topic=call.features.topic,
                standing=call.features.standing,
                infra=d.rule_id == "GATE-DETECTOR-FAILED",
            )
            with self._lock:
                self.engine.add(call.session_id, turn)
                late = self._pending.pop(d.decision_id, None)  # Tier 0b finished first
                if late:
                    self.engine.add_codes(call.session_id, agent_id, d.decision_id, late)
            self._policy = policy
            self.stats["observed"] += 1
            self._assess_act(policy, agent_id, call.session_id, now_ms)
        except Exception:  # noqa: BLE001 - the decision is already made and recorded
            log.exception("session observe failed")
            self.stats["errors"] += 1

    def _assess_act(self, policy: Any, agent_id: str, session_id: str, now_ms: int) -> None:
        """Assess the window at ``now_ms`` and apply the case rule and the pause rule."""
        cfg, cap = self.config_for(policy, agent_id)
        with self._lock:
            a = self.engine.assess(session_id, agent_id, now_ms, cfg, cap)
            rows = (
                timeline(self.engine.turns(session_id, agent_id))
                if a and (a.case_due or a.pause_due)
                else []
            )
            mono = time.monotonic()
            if mono - self._forgot > FORGET_EVERY_S:
                self._forgot = mono
                self.engine.forget(now_ms - lookback_s(cfg.window_s) * 1000)
        if a is None or not (a.case_due or a.pause_due):
            return
        with self._act_lock:
            res = self.actions.act(a, cfg, rows, source="in_request")
        if res.case_opened:
            self.stats["cases"] += 1
        if res.pause_set and res.pause_id:
            self.stats["pauses"] += 1
            with self._lock:
                self._pauses[(agent_id, session_id)] = (
                    res.pause_id,
                    now_ms + cfg.cooldown_s * 1000,
                    cfg.pause_scope,
                )
                self._local[(agent_id, session_id)] = time.monotonic()

    def _warm(self, policy: Any, now: datetime, exclude: str) -> None:
        """Cold start: rebuild the windows from stored gate decisions (once per process)."""
        self._warmed = True
        try:
            from datetime import timedelta

            from supervisor.monitors.session_batch import load_turns

            span = lookback_s(int(getattr(self.settings, "session_window_s", 1800)))
            loaded = load_turns(self.ctx, policy, now - timedelta(seconds=span), now)
            with self._lock:
                for (_, sid), turns in loaded.items():
                    for t in turns:
                        if t.event_id != exclude:
                            self.engine.add(sid, t)
        except Exception:  # noqa: BLE001 - a cold window only means less history
            log.exception("session window warm-up failed")

    def note_codes(self, call: SessionCall, agent_id: str, event_id: str, kinds: list[str]) -> None:
        """Tier 0b ran after the decision: its finding kinds join the turn, and the window is
        assessed again at that turn's time (a late finding can be the K-th hit)."""
        try:
            with self._lock:
                ok = self.engine.add_codes(call.session_id, agent_id, event_id, kinds)
                if not ok:  # the turn is not stored yet: park the codes, oldest out first
                    self._pending[event_id] = list(kinds)
                    while len(self._pending) > MAX_PENDING:
                        self._pending.popitem(last=False)
                    return
                turns = self.engine.turns(call.session_id, agent_id)
                ts = next((t.ts_ms for t in reversed(turns) if t.event_id == event_id), None)
            policy = self._policy
            if ts is not None and policy is not None:
                self._assess_act(policy, agent_id, call.session_id, ts)
        except Exception:  # noqa: BLE001
            log.exception("session note_codes failed")
            self.stats["errors"] += 1


__all__ = [
    "PAUSE_RULE",
    "BaselineTools",
    "SessionCall",
    "SessionGate",
    "epoch_ms",
    "finding_codes",
]

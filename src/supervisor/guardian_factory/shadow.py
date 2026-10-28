"""Shadow run of a guardian definition on live gate traffic (WP-G3, GUARDIAN_SHADOW).

``DetectorGate.shadow`` holds one :class:`ShadowRunner`. After the real detector pass of a call
(``DetectorGate.prepare``, outside the gate lock) the gate calls ``observe``. For each definition
in state ``shadow`` whose scope fits the call, the runner builds the detector with
``adapter.build`` and runs it in log-only mode:

* a finding becomes one row of ``guardian_shadow_finding``: call reference, stage, code, count and
  a hash. No masked value text, no argument text. Nothing is blocked, redacted or returned: the
  gate decision is the same with and without the runner (a test proves it).
* the budget is ``GUARDIAN_SHADOW_BUDGET_MS`` per call, over all shadow detectors together. A
  shadow detector that would start after the budget is used is skipped and counted
  (``skipped_budget`` of the day row).
* a regex, keyword or policy guardian runs inline (microseconds). A classifier or judge guardian
  needs a model; it runs on one worker thread behind a short queue, so the gate never waits for
  it; a full queue counts as skipped.
* day counters (calls in scope, calls that would act, skipped, findings) are kept in memory and
  written to ``guardian_shadow_day`` every ``SHADOW_FLUSH_CALLS`` calls or ``SHADOW_FLUSH_S``
  seconds, and by ``flush``.

``observe`` never raises. With the flag off the gate has no runner and this module is not called.
"""

from __future__ import annotations

import copy
import logging
import threading
import time
import uuid
from collections.abc import Callable, Mapping
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from typing import Any

from supervisor.guardian_factory import adapter, attach, caps
from supervisor.guardian_factory.definition import validate_definition

log = logging.getLogger("supervisor.guardian_factory")
FINDINGS = "guardian_shadow_finding"
DAYS = "guardian_shadow_day"
DEFS = "guardian_def"


def enabled(settings: Any) -> bool:
    return bool(
        getattr(settings, "guardian_factory", False)
        and getattr(settings, "guardian_shadow", False)
        and getattr(settings, "detectors_enabled", False)
    )


def _count_of(f: Any) -> int:
    n = int(getattr(f, "masked_count", 0) or 0)
    if n <= 0:
        n = sum(int(getattr(e, "count", 0) or 0) for e in getattr(f, "entities", ()) or ())
    return max(1, n)


class ShadowRunner:
    def __init__(
        self,
        state: Any,
        settings: Any,
        *,
        registry: Any = None,
        chat: Any = None,
        masker: Any = None,
        now: Callable[[], datetime] | None = None,
        perf: Callable[[], int] = time.perf_counter_ns,
        ttl_s: float = caps.SHADOW_CACHE_S,
    ) -> None:
        self.state = state
        self.settings = settings
        self.registry = registry
        self.chat = chat
        self.masker = masker
        self._now = now or (lambda: datetime.now(UTC))
        self._perf = perf
        self.ttl_s = ttl_s
        self.budget_ns = int(getattr(settings, "guardian_shadow_budget_ms", 20)) * 1_000_000
        self._lock = threading.Lock()
        self._flush_lock = threading.Lock()
        self._loaded = -1.0
        self._gen = -1
        self._built: dict[tuple[str, int, int], tuple[Any, Any]] = {}
        self._active: list[tuple[Any, Any]] = []
        self._counts: dict[tuple[str, int, str], list[int]] = {}
        self._calls_since_flush = 0
        self._last_flush = time.monotonic()
        self._pool: ThreadPoolExecutor | None = None
        self._pending = 0

    # ------------------------------------------------------------------ the shadow list
    def active(self) -> list[tuple[Any, Any]]:
        """(definition, detector) of each guardian in state shadow."""
        now = time.monotonic()
        with self._lock:
            if self._gen == attach.generation() and now - self._loaded < self.ttl_s:
                return self._active
            out: list[tuple[Any, Any]] = []
            try:
                rows = [dict(r) for r in self.state.query(DEFS, {"state": "shadow"})]
            except Exception:  # noqa: BLE001
                log.exception("shadow list not read")
                return self._active
            keep: dict[tuple[str, int, int], tuple[Any, Any]] = {}
            for r in rows:
                key = (str(r["def_id"]), int(r["version"]), int(r.get("row_version") or 1))
                try:
                    pair = self._built.get(key)
                    if pair is None:
                        d = validate_definition(attach.body_of(r))
                        if (
                            d.type in caps.MODEL_TYPES
                            and self.chat is None
                            and d.type != "classifier"
                        ):
                            continue  # a judge guardian needs the gateway model
                        det = adapter.build(
                            d,
                            delegates=attach.delegates_of(self.registry) if self.registry else {},
                            chat=self.chat,
                            masker=self.masker,
                            today=lambda: self._now().date(),
                        )
                        pair = (d, det)
                    keep[key] = pair
                    out.append(pair)
                except Exception:  # noqa: BLE001 - one bad definition does not stop the others
                    log.exception("shadow guardian %s not built", key[0])
            self._built, self._active = keep, out
            self._loaded, self._gen = now, attach.generation()
            return out

    # ------------------------------------------------------------------ the hook
    def observe(self, view: Mapping[str, Any], direction: str, call_ref: str) -> None:
        try:
            self._observe(view, direction, call_ref)
        except Exception:  # noqa: BLE001 - the shadow run never touches the gate
            log.exception("shadow observe failed")

    def _observe(self, view: Mapping[str, Any], direction: str, call_ref: str) -> None:
        defs = self.active()
        if not defs:
            return
        t0 = self._perf()
        meta = view.get("meta") or {}
        day = self._now().strftime("%Y-%m-%d")
        touched = False
        for d, det in defs:
            if direction not in det.sides or not det.applies(meta):
                continue
            touched = True
            key = (d.id, d.lifecycle.version, day)
            self._add(key, calls=1)
            if self._perf() - t0 >= self.budget_ns:
                self._add(key, skipped=1)
                continue
            if d.type in caps.MODEL_TYPES:
                self._submit(d, det, view, direction, call_ref, key)
                continue
            self._run(d, det, view, direction, call_ref, key)
        if touched:
            self._maybe_flush()

    def _run(
        self,
        d: Any,
        det: Any,
        view: Mapping[str, Any],
        direction: str,
        call_ref: str,
        key: tuple[str, int, str],
    ) -> None:
        found = [
            f
            for f in det.evaluate(view, {}, direction)
            if getattr(f, "not_executed_reason", None) is None and getattr(f, "fired", True)
        ]
        if not found:
            return
        meta = view.get("meta") or {}
        now = self._now()
        for f in found:
            self.state.insert(
                FINDINGS,
                {
                    "finding_id": "gsf_" + uuid.uuid4().hex[:24],
                    "def_id": d.id,
                    "version": d.lifecycle.version,
                    "agent_id": str(meta.get("agent_id") or "")[:64],
                    "call_ref": str(call_ref or "")[:128],
                    "stage": d.stage,
                    "finding_code": f.code[:128],
                    "count": _count_of(f),
                    "value_hash": f.digest(),
                    "would_action": d.action_on_fail,
                    "reviewed": None,
                    "reviewed_by": None,
                    "created_at": now,
                },
            )
        self._add(key, would=1, findings=len(found))

    def _submit(
        self,
        d: Any,
        det: Any,
        view: Mapping[str, Any],
        direction: str,
        call_ref: str,
        key: tuple[str, int, str],
    ) -> None:
        with self._lock:
            if self._pending >= caps.SHADOW_MODEL_QUEUE:
                full = True
            else:
                full = False
                self._pending += 1
                if self._pool is None:
                    self._pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix="gf-shadow")
        if full:
            self._add(key, skipped=1)
            return
        snap = copy.deepcopy(dict(view))

        def work() -> None:
            try:
                self._run(d, det, snap, direction, call_ref, key)
            except Exception:  # noqa: BLE001
                log.exception("shadow model check failed")
            finally:
                with self._lock:
                    self._pending -= 1

        assert self._pool is not None  # noqa: S101
        self._pool.submit(work)

    def join(self) -> None:
        """Wait for the model checks in the queue (tests, shutdown)."""
        pool = self._pool
        if pool is not None:
            pool.submit(lambda: None).result(timeout=30)

    # ------------------------------------------------------------------ counters
    def _add(
        self,
        key: tuple[str, int, str],
        *,
        calls: int = 0,
        would: int = 0,
        skipped: int = 0,
        findings: int = 0,
    ) -> None:
        with self._lock:
            c = self._counts.setdefault(key, [0, 0, 0, 0])
            c[0] += calls
            c[1] += would
            c[2] += skipped
            c[3] += findings
            self._calls_since_flush += calls

    def _maybe_flush(self) -> None:
        if (
            self._calls_since_flush >= caps.SHADOW_FLUSH_CALLS
            or time.monotonic() - self._last_flush >= caps.SHADOW_FLUSH_S
        ):
            self.flush()

    def flush(self) -> None:
        """Write the day counters to ``guardian_shadow_day`` (adds to the stored row)."""
        with self._flush_lock:
            self._flush()

    def _flush(self) -> None:
        with self._lock:
            take, self._counts = self._counts, {}
            self._calls_since_flush = 0
            self._last_flush = time.monotonic()
        for (def_id, version, day), c in take.items():
            try:
                self._write_day(def_id, version, day, c)
            except Exception:  # noqa: BLE001
                log.exception("shadow day counters not written")
                with self._lock:
                    cur = self._counts.setdefault((def_id, version, day), [0, 0, 0, 0])
                    for i in range(4):
                        cur[i] += c[i]

    def _write_day(self, def_id: str, version: int, day: str, c: list[int]) -> None:
        key = {"def_id": def_id, "version": version, "day": day}
        row = self.state.get(DAYS, key)
        if row is None:
            self.state.insert(
                DAYS,
                {
                    **key,
                    "calls_seen": c[0],
                    "would_act": c[1],
                    "skipped_budget": c[2],
                    "findings_n": c[3],
                    "chained": False,
                },
            )
            return
        self.state.update(
            DAYS,
            key,
            {
                "calls_seen": int(row["calls_seen"]) + c[0],
                "would_act": int(row["would_act"]) + c[1],
                "skipped_budget": int(row["skipped_budget"]) + c[2],
                "findings_n": int(row["findings_n"]) + c[3],
            },
            row["row_version"],
        )

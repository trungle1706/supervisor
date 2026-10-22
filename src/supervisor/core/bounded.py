"""A small bounded executor for guard model calls (WP-D3 review fix M1).

``Bounded.run(fn, timeout_s)`` runs ``fn`` in its own daemon thread and waits at most
``timeout_s`` for it. At most ``slots`` calls are in flight; with no free slot the call fails at
once with ``GuardModelError(reason="timed_out")``. A call that ran out of time keeps its thread
until the call ends (Python cannot kill one) but the caller is free, and the slot stays taken, so
a slow or trickling endpoint can hold at most ``slots`` threads, never the gate's shared pool.
"""

from __future__ import annotations

import threading
from collections.abc import Callable
from typing import Any

from supervisor.core.errors import GuardModelError

DEFAULT_SLOTS = 4


class Bounded:
    def __init__(self, slots: int = DEFAULT_SLOTS) -> None:
        self._sem = threading.BoundedSemaphore(slots)

    def run(self, fn: Callable[[], Any], timeout_s: float) -> Any:
        if timeout_s <= 0:
            raise GuardModelError("guard model has no time left", "timed_out")
        if not self._sem.acquire(blocking=False):
            raise GuardModelError("guard model is busy (all call slots taken)", "timed_out")
        box: dict[str, Any] = {}
        done = threading.Event()

        def target() -> None:
            try:
                box["value"] = fn()
            except BaseException as exc:  # noqa: BLE001 - handed back to the caller
                box["error"] = exc
            finally:
                self._sem.release()
                done.set()

        try:
            threading.Thread(target=target, name="guard-model", daemon=True).start()
        except BaseException:
            self._sem.release()
            raise
        if not done.wait(timeout_s):
            raise GuardModelError("guard model did not answer in time", "timed_out")
        if "error" in box:
            raise box["error"]
        return box["value"]

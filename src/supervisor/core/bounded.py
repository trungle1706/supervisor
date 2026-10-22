"""Run a function with a hard deadline in a daemon thread (WP-D1).

Python cannot kill a thread. A function that hangs keeps its thread until it returns, but the
caller gets ``TimeoutError`` at the deadline and goes on. A ``BoundedSlots`` value caps how many
such threads exist at once: with no free slot the call is not started and ``NoSlot`` is raised.
Pure standard library, no I/O of its own.
"""

from __future__ import annotations

import threading
from collections.abc import Callable
from typing import Any


class NoSlot(Exception):
    """Every thread slot is held (hung functions)."""


class BoundedSlots:
    """A fixed number of thread slots shared by the callers of one subsystem."""

    def __init__(self, n: int) -> None:
        self._sem = threading.BoundedSemaphore(n)

    def call(self, fn: Callable[[], Any], timeout_s: float, name: str = "bounded") -> Any:
        """Run ``fn`` and wait at most ``timeout_s``. Raises ``TimeoutError`` on a deadline miss,
        ``NoSlot`` when no slot is free, else re-raises what ``fn`` raised."""
        if not self._sem.acquire(blocking=False):
            raise NoSlot
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
            threading.Thread(target=target, name=name, daemon=True).start()
        except BaseException:
            self._sem.release()
            raise
        if not done.wait(timeout_s):
            raise TimeoutError
        if "error" in box:
            raise box["error"]
        return box["value"]

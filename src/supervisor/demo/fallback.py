"""Deadline and replay fallback for the demo steps that call a model.

Rule (analysis 04 section 4): if a step is not green 20 s after start, switch to the
recorded twin for that step and say so. Only steps that call a model (judge, onboarding)
have a recorded twin. The gate block, the pause and the chain break are never replayed:
those steps always run live, and a failure there is a ``[FAIL]``.

Recorded twins live in ``data/fixtures/demo_replay/<step>.json``:

    {"step": "judge-DEMO-2", "label": "RECORDED ...", "recorded_at": "...",
     "source": "...", "lines": ["[OK] ...", ...]}

Every line shown from a twin is prefixed ``[REPLAY]``.
"""

from __future__ import annotations

import json
import threading
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from supervisor.config import REPO_ROOT

REPLAY_DIR = REPO_ROOT / "data" / "fixtures" / "demo_replay"
DEFAULT_DEADLINE_S = 20.0
REPLAY_TAG = "[REPLAY]"
# Steps that may be replayed. Gate, pause and tamper steps are never in this set.
REPLAYABLE_PREFIXES = ("judge-", "onboard-")


@dataclass
class DeadlineResult:
    ok: bool
    value: Any = None
    error: str | None = None
    timed_out: bool = False


def run_with_deadline(fn: Callable[[], Any], deadline_s: float) -> DeadlineResult:
    """Run ``fn`` in a worker thread; give up waiting after ``deadline_s``.

    A late worker keeps running in the background (daemon thread); whatever it writes is
    real evidence. The caller only stops waiting for it."""
    box: dict[str, Any] = {}

    def work() -> None:
        try:
            box["value"] = fn()
        except Exception as exc:  # noqa: BLE001 - reported to the caller as a failed step
            box["error"] = f"{type(exc).__name__}: {exc}"

    worker = threading.Thread(target=work, daemon=True, name="demo-step")
    worker.start()
    worker.join(deadline_s)
    if worker.is_alive():
        return DeadlineResult(False, error=f"not done after {deadline_s:.0f} s", timed_out=True)
    if "error" in box:
        return DeadlineResult(False, error=box["error"])
    return DeadlineResult(True, value=box.get("value"))


def is_replayable(step: str) -> bool:
    return step.startswith(REPLAYABLE_PREFIXES)


def fixture_path(step: str, replay_dir: Path | None = None) -> Path:
    return (replay_dir or REPLAY_DIR) / f"{step}.json"


def load_twin(step: str, replay_dir: Path | None = None) -> dict[str, Any] | None:
    if not is_replayable(step):
        raise ValueError(f"step {step!r} must run live; it has no recorded twin")
    path = fixture_path(step, replay_dir)
    if not path.is_file():
        return None
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict) or not isinstance(data.get("lines"), list):
        return None
    return data


def replay_lines(twin: dict[str, Any]) -> list[str]:
    """The twin's lines, each labelled ``[REPLAY]``, after a header naming the recording."""
    head = (
        f"{REPLAY_TAG} recorded twin of step {twin.get('step')}: {twin.get('label')} "
        f"(recorded {twin.get('recorded_at')})"
    )
    return [head, *(f"{REPLAY_TAG} {line}" for line in twin["lines"])]


def record_twin(
    step: str,
    lines: Sequence[str],
    *,
    source: str,
    replay_dir: Path | None = None,
) -> Path:
    """Write the recorded twin of a live step (``runbook --record``)."""
    if not is_replayable(step):
        raise ValueError(f"step {step!r} must run live; it cannot be recorded as a twin")
    path = fixture_path(step, replay_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    data = {
        "step": step,
        "label": "RECORDED live run of the same code (fixture, synthetic data)",
        "recorded_at": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "source": source,
        "lines": [line for line in lines if not line.startswith(REPLAY_TAG)],
    }
    path.write_text(
        json.dumps(data, indent=2, sort_keys=True, ensure_ascii=True) + "\n", encoding="utf-8"
    )
    return path


__all__ = [
    "DEFAULT_DEADLINE_S",
    "REPLAYABLE_PREFIXES",
    "REPLAY_DIR",
    "REPLAY_TAG",
    "DeadlineResult",
    "fixture_path",
    "is_replayable",
    "load_twin",
    "record_twin",
    "replay_lines",
    "run_with_deadline",
]

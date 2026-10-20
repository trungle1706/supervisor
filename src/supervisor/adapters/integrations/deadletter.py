"""Dead-letter file for outbound sends that failed after their retries (WP21).

One JSON object per line: ``{"ts", "kind", "key", "attempts", "error", "payload"}``. The
payload is exactly what would have been sent (ids, hashes, masked text), so the file holds
nothing the SIEM or webhook would not have received. ``replay`` re-sends the entries through
a callable and keeps the ones that fail again. The idempotency ``key`` makes a replay safe
for a receiver that deduplicates.
"""

from __future__ import annotations

import json
import os
import threading
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


class DeadLetter:
    def __init__(self, path: Path) -> None:
        self.path = Path(path)
        self._lock = threading.Lock()

    def put(self, kind: str, key: str, payload: Any, error: str, attempts: int) -> None:
        rec = {
            "ts": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z",
            "kind": kind,
            "key": key,
            "attempts": attempts,
            "error": error[:300],
            "payload": payload,
        }
        line = json.dumps(rec, sort_keys=True, ensure_ascii=True, separators=(",", ":"))
        with self._lock:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with self.path.open("a", encoding="utf-8", newline="\n") as fh:
                fh.write(line + "\n")

    def entries(self) -> list[dict[str, Any]]:
        try:
            text = self.path.read_text(encoding="utf-8")
        except OSError:
            return []
        out = []
        for line in text.splitlines():
            try:
                out.append(json.loads(line))
            except ValueError:
                continue  # a torn last line: skip it, never crash the sender
        return out

    def count(self) -> int:
        return len(self.entries())

    def replay(self, send: Callable[[dict[str, Any]], None]) -> tuple[int, int]:
        """Re-send every entry. Returns (sent, still_failing); failing entries stay."""
        with self._lock:
            entries = self.entries()
            keep: list[dict[str, Any]] = []
            sent = 0
            for e in entries:
                try:
                    send(e)
                    sent += 1
                except Exception:  # noqa: BLE001 - keep the entry for the next replay
                    keep.append(e)
            tmp = self.path.with_name(self.path.name + f".{os.getpid()}.tmp")
            if keep:
                tmp.write_text(
                    "".join(
                        json.dumps(e, sort_keys=True, ensure_ascii=True, separators=(",", ":"))
                        + "\n"
                        for e in keep
                    ),
                    encoding="utf-8",
                    newline="\n",
                )
                os.replace(tmp, self.path)
            elif entries:
                self.path.unlink(missing_ok=True)
            return sent, len(keep)


__all__ = ["DeadLetter"]

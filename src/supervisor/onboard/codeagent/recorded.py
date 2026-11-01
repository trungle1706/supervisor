"""Record and replay a model, so the eval and the tests run without one.

``RecordingChat`` wraps a real ``ChatModel`` and appends each call to a JSONL file:
``{"key": sha256(messages + schema), "response": {...}}``. ``ReplayChat`` answers from that file
and fails loudly on a request it has not recorded (the prompt changed: record again). A replayed
model is labelled ``recorded:<model id>`` and is never presented as a live model.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from supervisor.core.ports import ChatModel


def request_key(messages: Sequence[Mapping[str, str]], schema: Mapping[str, Any]) -> str:
    blob = json.dumps(
        {"m": [dict(m) for m in messages], "s": schema}, sort_keys=True, ensure_ascii=False
    )
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


class RecordingChat:
    is_mock = False

    def __init__(self, inner: ChatModel, path: str | Path) -> None:
        self.inner = inner
        self.path = Path(path)
        self.family = inner.family
        self.model_id = inner.model_id
        self.calls = 0
        self.seconds = 0.0

    def complete_json(
        self,
        messages: Sequence[Mapping[str, str]],
        json_schema: Mapping[str, Any],
        timeout_s: float | None = None,
    ) -> Mapping[str, Any]:
        import time

        t0 = time.monotonic()
        out = self.inner.complete_json(messages, json_schema, timeout_s)  # type: ignore[arg-type]
        self.seconds += time.monotonic() - t0
        self.calls += 1
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("a", encoding="utf-8") as fh:
            fh.write(
                json.dumps(
                    {"key": request_key(messages, json_schema), "response": out}, ensure_ascii=False
                )
                + "\n"
            )
        return out


class ReplayChat:
    is_mock = False  # the recorded answers came from a real model

    def __init__(self, path: str | Path, model_id: str = "recorded") -> None:
        self.family = "recorded"
        self.model_id = f"recorded:{model_id}"
        self._answers: dict[str, list[Mapping[str, Any]]] = {}
        for line in Path(path).read_text(encoding="utf-8").splitlines():
            if line.strip():
                row = json.loads(line)
                self._answers.setdefault(row["key"], []).append(row["response"])
        self._used: dict[str, int] = {}
        self.calls = 0

    def complete_json(
        self,
        messages: Sequence[Mapping[str, str]],
        json_schema: Mapping[str, Any],
        timeout_s: float | None = None,
    ) -> Mapping[str, Any]:
        key = request_key(messages, json_schema)
        rows = self._answers.get(key)
        if not rows:
            raise LookupError("request not in the recording (prompt changed? record again)")
        i = self._used.get(key, 0)
        self._used[key] = i + 1
        self.calls += 1
        return rows[min(i, len(rows) - 1)]

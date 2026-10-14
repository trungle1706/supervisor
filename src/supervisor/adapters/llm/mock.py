"""MockChat: deterministic ChatModel for tests, demos and offline laptops.

* ``is_mock = True``; ``model_id`` always contains ``mock`` (verdicts must be labelled).
* Scripted responses by scenario key: ``chat.add_script("task-1", [r1, r2])`` then
  ``with chat.scenario("task-1"): ...``. Each call pops the next response of the active
  scenario. A script entry may be a callable ``f(messages) -> dict``.
* With no script (or when a script runs out) it synthesises a minimal instance of the
  JSON schema from a seeded RNG.
* Every response is checked against the schema before it is returned, so callers always
  get schema-valid output; an invalid script entry raises ``ValueError`` (a test bug).
"""

from __future__ import annotations

import copy
import random
from collections.abc import Callable, Iterator, Mapping, Sequence
from contextlib import contextmanager
from typing import Any

from supervisor.adapters.llm import jsonschema_lite

ScriptEntry = Mapping[str, Any] | Callable[[Sequence[Mapping[str, str]]], Mapping[str, Any]]


class MockChat:
    is_mock = True

    def __init__(
        self,
        seed: int = 0,
        scripts: Mapping[str, Sequence[ScriptEntry]] | None = None,
        *,
        family: str = "mock",
        model_id: str = "mock-chat-v1",
    ) -> None:
        if "mock" not in model_id:
            raise ValueError("MockChat model_id must contain 'mock'")
        self.family = family
        self.model_id = model_id
        self.seed = seed
        self._rng = random.Random(seed)  # noqa: S311 - deterministic test double
        self._scripts: dict[str, list[ScriptEntry]] = {
            k: list(v) for k, v in (scripts or {}).items()
        }
        self._cursor: dict[str, int] = {}
        self._active: str | None = None
        self.calls: list[dict[str, Any]] = []

    # -- scripting ---------------------------------------------------------------
    def add_script(self, key: str, responses: Sequence[ScriptEntry]) -> None:
        self._scripts[key] = list(responses)
        self._cursor.pop(key, None)

    @contextmanager
    def scenario(self, key: str) -> Iterator[MockChat]:
        previous, self._active = self._active, key
        self._cursor[key] = 0
        try:
            yield self
        finally:
            self._active = previous

    def remaining(self, key: str) -> int:
        return len(self._scripts.get(key, ())) - self._cursor.get(key, 0)

    # -- ChatModel ---------------------------------------------------------------
    def complete_json(
        self,
        messages: Sequence[Mapping[str, str]],
        json_schema: Mapping[str, Any],
        timeout_s: float | None = None,
    ) -> Mapping[str, Any]:
        key = self._active
        response: Mapping[str, Any] | None = None
        if key is not None and self.remaining(key) > 0:
            entry = self._scripts[key][self._cursor[key]]
            self._cursor[key] += 1
            response = entry(messages) if callable(entry) else entry
        if response is None:
            response = synthesize(json_schema, self._rng)
        response = copy.deepcopy(dict(response))
        errs = jsonschema_lite.errors(response, json_schema)
        if errs:
            raise ValueError(f"MockChat script for {key!r} does not match the schema: {errs[:3]}")
        self.calls.append({"scenario": key, "n_messages": len(messages), "response": response})
        return response


def synthesize(schema: Mapping[str, Any], rng: random.Random) -> Any:
    """Smallest deterministic instance of ``schema`` (subset of JSON Schema)."""
    if "const" in schema:
        return schema["const"]
    if "enum" in schema:
        return rng.choice(list(schema["enum"]))
    for key in ("anyOf", "oneOf"):
        if key in schema:
            return synthesize(schema[key][0], rng)
    t = schema.get("type", "object")
    if isinstance(t, list):
        t = next((x for x in t if x != "null"), "null")
    if t == "object":
        props = schema.get("properties", {})
        return {k: synthesize(props.get(k, {}), rng) for k in schema.get("required", ())}
    if t == "array":
        n = schema.get("minItems", 0)
        return [synthesize(schema.get("items", {}), rng) for _ in range(n)]
    if t == "string":
        n = max(schema.get("minLength", 0), 4)
        n = min(n, schema.get("maxLength", n))
        return "mock" + "x" * max(0, n - 4) if n >= 4 else "m" * n
    if t in ("integer", "number"):
        lo = int(schema.get("minimum", 0))
        hi = int(schema.get("maximum", lo + 100))
        return rng.randint(lo, max(lo, hi))
    if t == "boolean":
        return False
    return None

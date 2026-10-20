"""Fake detectors for contract and gate tests."""

from __future__ import annotations

import time
from collections.abc import Callable, Mapping
from typing import Any

from supervisor.core.detectors import Finding, SettingField, SettingsSchema


class FakeDetector:
    """A detector whose behaviour a test scripts. ``fn(payload, settings, direction)``."""

    category = "test"
    version = "1.0.0"
    protocols = ("all",)
    presets = {"strict": 3000, "balanced": 5000, "lenient": 7000}

    def __init__(
        self,
        slug: str = "fake",
        fn: Callable[[Mapping[str, Any], Mapping[str, Any], str], list[Finding]] | None = None,
        sides: tuple[str, ...] = ("input", "output"),
        schema: SettingsSchema | None = None,
        protocols: tuple[str, ...] = ("all",),
    ) -> None:
        self.slug = slug
        self.name = f"Fake {slug}"
        self.sides = sides
        self.protocols = protocols
        self.settings_schema = schema or SettingsSchema()
        self.fn = fn or (lambda p, s, d: [])
        self.calls = 0

    def evaluate(
        self, payload: Mapping[str, Any], settings: Mapping[str, Any], direction: str
    ) -> list[Finding]:
        self.calls += 1
        return self.fn(payload, settings, direction)


def boom(payload: Mapping[str, Any], settings: Mapping[str, Any], direction: str) -> list[Finding]:
    raise RuntimeError("raw text that must never be echoed: 0912345678")


def slow(ms: int) -> Callable[[Mapping[str, Any], Mapping[str, Any], str], list[Finding]]:
    def run(
        payload: Mapping[str, Any], settings: Mapping[str, Any], direction: str
    ) -> list[Finding]:
        time.sleep(ms / 1000)
        return []

    return run


def hint(action: str, score: int = 9000) -> FakeDetector:
    """A detector that always fires with the given action_hint."""

    def fn(
        payload: Mapping[str, Any], settings: Mapping[str, Any], direction: str
    ) -> list[Finding]:
        return [
            Finding(
                detector_slug="hinter",
                detector_id="hinter@1.0.0",
                code=f"hint.{action}",
                score_bp=score,
                threshold_bp=5000,
                action_hint=action,  # type: ignore[arg-type]
            )
        ]

    return FakeDetector("hinter", fn)


SETTING_SCHEMA = SettingsSchema(
    (
        SettingField("mode", "Mode", "enum", default="a", enum=("a", "b")),
        SettingField("limit", "Limit", "integer", default=3, minimum=1, maximum=10),
        SettingField("on", "On", "boolean", default=True),
        SettingField("ratio", "Ratio", "number", default=1.5, minimum=0, maximum=5),
        SettingField("name", "Name", "string", default="x", max_length=5),
        SettingField("tags", "Tags", "array", default=[], items="string", item_enum=("p", "q")),
        SettingField(
            "nested",
            "Nested",
            "object",
            default={"depth": 1},
            fields=(SettingField("depth", "Depth", "integer", default=1, minimum=0, maximum=3),),
        ),
        SettingField("must", "Must", "string", required=True),
    )
)

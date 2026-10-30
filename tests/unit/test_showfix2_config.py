"""Showcase fixes 2: schema $ref inlining, timeout settings, demo shadow minimum."""

from __future__ import annotations

import pytest

from supervisor.adapters.llm.jsonschema_lite import inline_refs
from supervisor.config import load_settings


def test_inline_refs_resolves_nested_defs() -> None:
    schema = {
        "type": "object",
        "properties": {
            "config": {
                "type": "object",
                "properties": {"rules": {"type": "array", "items": {"$ref": "#/$defs/R"}}},
                "$defs": {"R": {"type": "object", "properties": {"op": {"$ref": "#/$defs/Op"}}}},
            }
        },
        "$defs": {"Op": {"type": "string", "enum": ["eq", "gt"]}},
    }
    out = inline_refs(schema)
    rules = out["properties"]["config"]["properties"]["rules"]["items"]
    assert rules["properties"]["op"] == {"type": "string", "enum": ["eq", "gt"]}
    assert "$defs" not in str(out) and "$ref" not in str(out)
    assert "$defs" in schema  # the input is not changed


def test_inline_refs_cycle_is_cut_and_plain_schema_is_unchanged() -> None:
    node = {"type": "object", "properties": {"k": {"$ref": "#/$defs/N"}}}
    cyc = {"$ref": "#/$defs/N", "$defs": {"N": node}}
    out = inline_refs(cyc)
    assert out["properties"]["k"] == {}
    plain = {"type": "object", "properties": {"a": {"type": "string"}}}
    assert inline_refs(plain) == plain


@pytest.mark.parametrize(
    ("field", "env", "default"),
    [
        ("guardian_author_timeout_s", "GUARDIAN_AUTHOR_TIMEOUT_S", 30),
        ("factory_helper_timeout_s", "FACTORY_HELPER_TIMEOUT_S", 60),
        ("factory_judge_timeout_s", "FACTORY_JUDGE_TIMEOUT_S", 60),
        ("factory_call_timeout_s", "FACTORY_CALL_TIMEOUT_S", 90),
        ("lawagent_timeout_s", "LAWAGENT_TIMEOUT_S", 180),
    ],
)
def test_timeout_settings(
    monkeypatch: pytest.MonkeyPatch, field: str, env: str, default: int
) -> None:
    monkeypatch.setenv("SUPERVISOR_ENV_FILE", "/dev/null")
    monkeypatch.delenv(env, raising=False)
    assert getattr(load_settings(), field) == default
    cases = (("400", 400), ("5", 5), ("900", 900), ("4", default), ("901", default))
    for raw, want in (*cases, ("x", default), ("", default)):
        monkeypatch.setenv(env, raw)
        assert getattr(load_settings(), field) == want, raw


def test_shadow_min_hours_needs_showcase(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SUPERVISOR_ENV_FILE", "/dev/null")
    for k in ("GUARDIAN_SHADOW_MIN_HOURS", "SHOWCASE_ENABLED"):
        monkeypatch.delenv(k, raising=False)
    assert load_settings().effective_shadow_min_hours == 24
    monkeypatch.setenv("GUARDIAN_SHADOW_MIN_HOURS", "1")
    assert load_settings().effective_shadow_min_hours == 24  # showcase off: ignored
    monkeypatch.setenv("SHOWCASE_ENABLED", "1")
    assert load_settings().effective_shadow_min_hours == 1
    monkeypatch.setenv("GUARDIAN_SHADOW_MIN_HOURS", "0")
    assert load_settings().effective_shadow_min_hours == 0
    monkeypatch.setenv("GUARDIAN_SHADOW_MIN_HOURS", "500")
    assert load_settings().effective_shadow_min_hours == 24  # out of range: default
    monkeypatch.setenv("GUARDIAN_SHADOW_MIN_HOURS", "48")
    assert load_settings().effective_shadow_min_hours == 48

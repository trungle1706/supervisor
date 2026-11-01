"""W1: strict structured output needs ``additionalProperties: false`` on every object (hub fix of
``jsonschema_lite.strict_compatible``); the runtime schemas of the assessment agent must pass it."""

from __future__ import annotations

from typing import Any

from supervisor.adapters.llm import jsonschema_lite
from supervisor.factory import runtime as rt


def _objects(node: Any) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    if isinstance(node, dict):
        if "properties" in node and isinstance(node["properties"], dict):
            out.append(node)
        for v in node.values():
            out.extend(_objects(v))
    elif isinstance(node, list):
        for v in node:
            out.extend(_objects(v))
    return out


def test_strict_compatible_adds_additional_properties_false() -> None:
    schema = {
        "type": "object",
        "properties": {
            "a": {"type": "string", "maxLength": 5},
            "b": {
                "type": "array",
                "items": {"type": "object", "properties": {"c": {"type": "integer"}}},
            },
        },
    }
    out = jsonschema_lite.strict_compatible(schema)
    assert out["additionalProperties"] is False
    assert out["properties"]["b"]["items"]["additionalProperties"] is False
    assert out["properties"]["a"] == {"type": "string"}
    assert "additionalProperties" not in schema  # a copy, the input is untouched


def test_an_explicit_additional_properties_is_kept() -> None:
    schema = {"type": "object", "properties": {"a": {}}, "additionalProperties": True}
    assert jsonschema_lite.strict_compatible(schema)["additionalProperties"] is True
    open_map = {"type": "object", "additionalProperties": {"type": "string"}}
    assert jsonschema_lite.strict_compatible(open_map) == open_map  # no properties: left alone


def test_a_property_named_like_a_keyword_is_not_an_object_to_close() -> None:
    schema = {"type": "object", "properties": {"properties": {"type": "string"}}}
    out = jsonschema_lite.strict_compatible(schema)
    assert out["additionalProperties"] is False
    assert out["properties"]["properties"] == {"type": "string"}


def test_every_runtime_schema_is_closed_after_the_strict_copy() -> None:
    for schema in (rt.RESPONSE_SCHEMA, rt.EVAL_SCHEMA, rt.REVIEW_SCHEMA):
        sent = jsonschema_lite.strict_compatible(schema)
        objs = _objects(sent)
        assert objs and all(o.get("additionalProperties") is False for o in objs)
        assert "maxLength" not in str(sent)

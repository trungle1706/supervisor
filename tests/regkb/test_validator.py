from __future__ import annotations

from typing import Any

import pytest

from supervisor.regkb.errors import UnsupportedKeywordError
from supervisor.regkb.validator import validate


def paths(instance: Any, schema: Any, root: Any = None) -> list[str]:
    return [str(i) for i in validate(instance, schema, root)]


@pytest.mark.parametrize(
    ("typ", "good", "bad"),
    [
        ("object", {}, []),
        ("array", [], {}),
        ("string", "x", 1),
        ("boolean", True, 1),
        ("integer", 3, True),
        ("integer", 3, 3.5),
        ("null", None, 0),
    ],
)
def test_type(typ: str, good: Any, bad: Any) -> None:
    assert validate(good, {"type": typ}) == []
    assert validate(bad, {"type": typ})


def test_enum_const_distinguish_bool_and_int() -> None:
    assert validate("a", {"enum": ["a", "b"]}) == []
    assert validate("c", {"enum": ["a", "b"]})
    assert validate(1, {"const": 1}) == []
    assert validate(True, {"const": 1})
    assert validate(2, {"const": 1})


def test_string_rules() -> None:
    assert validate("ab1", {"pattern": "^[a-z]+[0-9]$"}) == []
    assert validate("1ab", {"pattern": "^[a-z]+[0-9]$"})
    assert validate("", {"minLength": 1})
    assert validate("x", {"minLength": 1}) == []


def test_array_rules() -> None:
    assert validate([], {"minItems": 1})
    assert validate([1, 1], {"uniqueItems": True})
    assert validate([1, True], {"uniqueItems": True}) == []
    assert validate([{"a": 1}, {"a": 1}], {"uniqueItems": True})
    out = paths([1, "x", 2], {"items": {"type": "integer"}})
    assert out == ["$[1]: expected integer, got str"]


def test_object_rules_and_paths() -> None:
    schema = {
        "type": "object",
        "required": ["a"],
        "properties": {
            "a": {"type": "string"},
            "b": {"type": "object", "properties": {"c": {"type": "integer"}}},
        },
        "additionalProperties": False,
    }
    assert paths({}, schema) == ["$: missing required property 'a'"]
    assert paths({"a": "x", "z": 1}, schema) == ["$.z: property is not allowed"]
    assert paths({"a": "x", "b": {"c": "no"}}, schema) == ["$.b.c: expected integer, got str"]


def test_additional_properties_schema() -> None:
    schema = {"properties": {"a": True}, "additionalProperties": {"type": "integer"}}
    assert validate({"a": "any", "b": 1}, schema) == []
    assert paths({"b": "x"}, schema) == ["$.b: expected integer, got str"]


def test_boolean_schemas() -> None:
    assert validate(5, True) == []
    assert validate(5, False)
    assert validate({"a": 1}, {"properties": {"a": False}})


def test_ref_local_and_root() -> None:
    root = {
        "$defs": {
            "n": {"type": "integer"},
            "tree": {"properties": {"kid": {"$ref": "#/$defs/tree"}, "v": {"$ref": "#/$defs/n"}}},
        },
        "$ref": "#/$defs/tree",
    }
    assert validate({"v": 1, "kid": {"v": 2}}, root) == []
    assert paths({"v": 1, "kid": {"v": "x"}}, root) == ["$.kid.v: expected integer, got str"]
    selfref = {"properties": {"next": {"$ref": "#"}}, "required": ["id"]}
    assert paths({"id": 1, "next": {}}, selfref) == ["$.next: missing required property 'id'"]


def test_ref_errors() -> None:
    with pytest.raises(UnsupportedKeywordError):
        validate(1, {"$ref": "#/$defs/missing"})
    with pytest.raises(UnsupportedKeywordError):
        validate(1, {"$ref": "other.json#/x"})


def test_any_of_and_all_of() -> None:
    schema = {"anyOf": [{"type": "string"}, {"type": "null"}]}
    assert validate(None, schema) == []
    assert validate("x", schema) == []
    assert paths(3, schema) == ["$: matches none of 2 alternatives"]
    both = {"allOf": [{"type": "object"}, {"required": ["a"]}, {"required": ["b"]}]}
    assert len(validate({}, both)) == 2


def test_all_of_with_sibling_properties_additional_properties_semantics() -> None:
    # 2020-12: additionalProperties sees only sibling properties, not those inside allOf.
    schema = {
        "allOf": [{"properties": {"a": {"type": "string"}}}],
        "additionalProperties": False,
        "properties": {"b": True},
    }
    assert paths({"a": "x"}, schema) == ["$.a: property is not allowed"]
    assert validate({"b": 1}, schema) == []
    listed = dict(schema, properties={"a": True, "b": True})
    assert validate({"a": "x", "b": 1}, listed) == []
    assert paths({"a": 5}, listed) == ["$.a: expected string, got int"]


def test_unknown_keyword_raises() -> None:
    with pytest.raises(UnsupportedKeywordError):
        validate(1, {"minimum": 0})
    with pytest.raises(UnsupportedKeywordError):
        validate(1, {"type": "number"})


def test_annotations_ignored() -> None:
    schema = {
        "$schema": "x",
        "$id": "y",
        "title": "t",
        "description": "d",
        "$defs": {},
        "type": "integer",
    }
    assert validate(1, schema) == []

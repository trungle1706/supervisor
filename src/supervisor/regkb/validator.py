"""Small JSON Schema (draft 2020-12 subset) validator. No third-party dependency.

Supported: type, properties, required, additionalProperties (bool or schema), enum, const,
pattern, minLength, minItems, uniqueItems, items, $ref (``#`` and ``#/...``), anyOf, allOf,
boolean schemas. ``additionalProperties`` sees only the sibling ``properties`` of the same
schema object (2020-12 rule). Annotation keywords are ignored; any other keyword raises
``UnsupportedKeywordError`` so a schema change does not pass unnoticed.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any

from supervisor.regkb.errors import UnsupportedKeywordError

ANNOTATIONS = frozenset({"$schema", "$id", "$comment", "title", "description", "$defs"})
KEYWORDS = frozenset(
    {
        "type",
        "properties",
        "required",
        "additionalProperties",
        "enum",
        "const",
        "pattern",
        "minLength",
        "minItems",
        "uniqueItems",
        "items",
        "$ref",
        "anyOf",
        "allOf",
    }
)
MAX_DEPTH = 64


@dataclass(frozen=True)
class Issue:
    path: str
    message: str

    def __str__(self) -> str:
        return f"{self.path}: {self.message}"


def _is_type(value: Any, name: str) -> bool:
    if name == "object":
        return isinstance(value, dict)
    if name == "array":
        return isinstance(value, list)
    if name == "string":
        return isinstance(value, str)
    if name == "boolean":
        return isinstance(value, bool)
    if name == "integer":
        return isinstance(value, int) and not isinstance(value, bool)
    if name == "null":
        return value is None
    raise UnsupportedKeywordError(f"unsupported type name {name!r} in schema")


def _same(a: Any, b: Any) -> bool:
    """JSON equality: True != 1."""
    return type(a) is type(b) and a == b


def _key(value: Any) -> str:
    return json.dumps(value, sort_keys=True, default=str)


def _name(value: Any) -> str:
    return "null" if value is None else type(value).__name__


class _Run:
    def __init__(self, root: Any) -> None:
        self.root = root
        self.issues: list[Issue] = []

    def resolve(self, ref: str) -> Any:
        if ref == "#":
            return self.root
        if not ref.startswith("#/"):
            raise UnsupportedKeywordError(f"unsupported $ref {ref!r} (only local refs)")
        node: Any = self.root
        for part in ref[2:].split("/"):
            part = part.replace("~1", "/").replace("~0", "~")
            if not isinstance(node, dict) or part not in node:
                raise UnsupportedKeywordError(f"$ref {ref!r} does not resolve")
            node = node[part]
        return node

    def check(self, value: Any, schema: Any, path: str, depth: int = 0) -> None:
        if depth > MAX_DEPTH:
            raise UnsupportedKeywordError(f"schema nesting deeper than {MAX_DEPTH} at {path}")
        if schema is True:
            return
        if schema is False:
            self.issues.append(Issue(path, "no value is allowed here"))
            return
        if not isinstance(schema, dict):
            raise UnsupportedKeywordError(f"schema at {path} is not an object or boolean")
        unknown = set(schema) - KEYWORDS - ANNOTATIONS
        if unknown:
            raise UnsupportedKeywordError(f"unsupported schema keyword(s): {sorted(unknown)}")
        if "$ref" in schema:
            self.check(value, self.resolve(schema["$ref"]), path, depth + 1)
        for sub in schema.get("allOf", []):
            self.check(value, sub, path, depth + 1)
        if "anyOf" in schema:
            self._any_of(value, schema["anyOf"], path, depth)
        self._scalar_rules(value, schema, path)
        if isinstance(value, dict):
            self._object_rules(value, schema, path, depth)
        if isinstance(value, list):
            self._array_rules(value, schema, path, depth)

    def _any_of(self, value: Any, branches: list[Any], path: str, depth: int) -> None:
        saved = self.issues
        for branch in branches:
            self.issues = []
            self.check(value, branch, path, depth + 1)
            if not self.issues:
                self.issues = saved
                return
        self.issues = saved
        self.issues.append(Issue(path, f"matches none of {len(branches)} alternatives"))

    def _scalar_rules(self, value: Any, schema: dict[str, Any], path: str) -> None:
        if "type" in schema:
            types = schema["type"] if isinstance(schema["type"], list) else [schema["type"]]
            if not any(_is_type(value, t) for t in types):
                self.issues.append(Issue(path, f"expected {'/'.join(types)}, got {_name(value)}"))
                return
        if "enum" in schema and not any(_same(value, e) for e in schema["enum"]):
            self.issues.append(Issue(path, f"{value!r} is not one of {schema['enum']}"))
        if "const" in schema and not _same(value, schema["const"]):
            self.issues.append(Issue(path, f"must equal {schema['const']!r}"))
        if isinstance(value, str):
            if "pattern" in schema and not re.search(schema["pattern"], value):
                self.issues.append(Issue(path, f"{value!r} does not match {schema['pattern']}"))
            if len(value) < schema.get("minLength", 0):
                self.issues.append(Issue(path, f"shorter than {schema['minLength']}"))

    def _object_rules(
        self, value: dict[str, Any], schema: dict[str, Any], path: str, depth: int
    ) -> None:
        props = schema.get("properties", {})
        for name in schema.get("required", []):
            if name not in value:
                self.issues.append(Issue(path, f"missing required property {name!r}"))
        for name, sub in props.items():
            if name in value:
                self.check(value[name], sub, f"{path}.{name}", depth + 1)
        if "additionalProperties" in schema:
            extra = schema["additionalProperties"]
            for name in value:
                if name in props:
                    continue
                if extra is False:
                    self.issues.append(Issue(f"{path}.{name}", "property is not allowed"))
                else:
                    self.check(value[name], extra, f"{path}.{name}", depth + 1)

    def _array_rules(self, value: list[Any], schema: dict[str, Any], path: str, depth: int) -> None:
        if len(value) < schema.get("minItems", 0):
            self.issues.append(Issue(path, f"fewer than {schema['minItems']} items"))
        if schema.get("uniqueItems") and len({_key(v) for v in value}) != len(value):
            self.issues.append(Issue(path, "items are not unique"))
        if "items" in schema:
            for i, item in enumerate(value):
                self.check(item, schema["items"], f"{path}[{i}]", depth + 1)


def validate(instance: Any, schema: Any, root: Any = None) -> list[Issue]:
    """Return all issues (empty list = valid). ``root`` is the document for ``$ref`` lookup."""
    run = _Run(root if root is not None else schema)
    run.check(instance, schema, "$")
    return run.issues

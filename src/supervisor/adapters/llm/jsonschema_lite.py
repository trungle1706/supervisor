"""Small JSON Schema checker (stdlib only) for the subset Supervisor uses.

Supported keywords: type (incl. list of types), enum, const, required, properties,
additionalProperties (bool or schema), items, minItems, maxItems, minLength, maxLength,
pattern, minimum, maximum, anyOf, oneOf. Unknown keywords are ignored. Booleans are not
integers here (``True`` fails ``"type": "integer"``). Floats are accepted only for
``"type": "number"``.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from typing import Any

_TYPES: dict[str, tuple[type, ...]] = {
    "object": (dict,),
    "array": (list, tuple),
    "string": (str,),
    "integer": (int,),
    "number": (int, float),
    "boolean": (bool,),
    "null": (type(None),),
}


def _is_type(value: Any, name: str) -> bool:
    if name in ("integer", "number") and isinstance(value, bool):
        return False
    return isinstance(value, _TYPES[name])


def errors(value: Any, schema: Mapping[str, Any], path: str = "$") -> list[str]:
    """Return a list of human-readable problems; empty list means valid."""
    out: list[str] = []
    t = schema.get("type")
    if t is not None:
        names = [t] if isinstance(t, str) else list(t)
        if not any(_is_type(value, n) for n in names):
            return [f"{path}: expected {t}, got {type(value).__name__}"]
    if "const" in schema and value != schema["const"]:
        out.append(f"{path}: must equal {schema['const']!r}")
    if "enum" in schema and value not in schema["enum"]:
        out.append(f"{path}: {value!r} not in enum")
    if isinstance(value, str):
        if len(value) < schema.get("minLength", 0):
            out.append(f"{path}: shorter than {schema['minLength']}")
        if "maxLength" in schema and len(value) > schema["maxLength"]:
            out.append(f"{path}: longer than {schema['maxLength']}")
        if "pattern" in schema and not re.search(schema["pattern"], value):
            out.append(f"{path}: does not match {schema['pattern']}")
    if _is_type(value, "number"):
        if "minimum" in schema and value < schema["minimum"]:
            out.append(f"{path}: below minimum {schema['minimum']}")
        if "maximum" in schema and value > schema["maximum"]:
            out.append(f"{path}: above maximum {schema['maximum']}")
    if isinstance(value, dict):
        for key in schema.get("required", ()):
            if key not in value:
                out.append(f"{path}: missing required {key!r}")
        props = schema.get("properties", {})
        extra = schema.get("additionalProperties", True)
        for key, item in value.items():
            if key in props:
                out.extend(errors(item, props[key], f"{path}.{key}"))
            elif extra is False:
                out.append(f"{path}: unexpected property {key!r}")
            elif isinstance(extra, Mapping):
                out.extend(errors(item, extra, f"{path}.{key}"))
    if isinstance(value, list | tuple):
        if len(value) < schema.get("minItems", 0):
            out.append(f"{path}: fewer than {schema['minItems']} items")
        if "maxItems" in schema and len(value) > schema["maxItems"]:
            out.append(f"{path}: more than {schema['maxItems']} items")
        if isinstance(schema.get("items"), Mapping):
            for i, item in enumerate(value):
                out.extend(errors(item, schema["items"], f"{path}[{i}]"))
    if "anyOf" in schema and not any(not errors(value, s, path) for s in schema["anyOf"]):
        out.append(f"{path}: matches none of anyOf")
    if "oneOf" in schema and sum(1 for s in schema["oneOf"] if not errors(value, s, path)) != 1:
        out.append(f"{path}: must match exactly one of oneOf")
    return out


def is_valid(value: Any, schema: Mapping[str, Any]) -> bool:
    return not errors(value, schema)

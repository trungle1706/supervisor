"""Condition trees for the assignment rules and the Decision 33 flow (WP-G2).

Pure Python: no file, no SQL, no clock, no model. A condition is a small tree:

    {all: [node, ...]}   {any: [node, ...]}   {not: node}
    {field: <name>, <operator>: <value>}      operators: eq, in, gte, is_true

``parse`` checks the shape against a field table and fails at load (``RulesError``) on an unknown
key, field, operator or value. ``evaluate`` returns a ``Trace`` that keeps what was looked at, so
the same facts always give the same result and the same explanation. A missing fact (``None``)
makes a leaf false.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from supervisor.core.errors import SupervisorError

OPERATORS: tuple[str, ...] = ("eq", "in", "gte", "is_true")
COMBINERS: tuple[str, ...] = ("all", "any", "not")
MAX_DEPTH = 8
MAX_NODES = 200


class RulesError(SupervisorError):
    """A bad rules file, flow file or rule input (HTTP 400 at a route)."""


@dataclass(frozen=True)
class FieldSpec:
    """What a condition may say about one field.

    ``kind``: ``enum`` (one of ``values``), ``ordered`` (``values`` low to high; ``gte`` works),
    ``bool``, ``int`` (``gte`` works) or ``set`` (several text values; ``eq``/``in`` are true when
    any value matches; ``values`` may be ``None`` for free text)."""

    kind: str
    values: tuple[str, ...] | None = None


@dataclass(frozen=True)
class Node:
    op: str  # all | any | not | leaf
    children: tuple[Node, ...] = ()
    field: str = ""
    operator: str = ""
    value: Any = None


@dataclass(frozen=True)
class Trace:
    """The result of one node and what was looked at. ``actual`` is the fact seen by a leaf."""

    op: str
    result: bool
    children: tuple[Trace, ...] = ()
    field: str = ""
    operator: str = ""
    value: Any = None
    actual: Any = None


FieldLookup = Callable[[str], FieldSpec | None]


def _err(where: str, message: str) -> RulesError:
    return RulesError(f"{where}: {message}")


def parse(
    node: Any,
    lookup: FieldLookup,
    where: str,
    *,
    _depth: int = 0,
    _count: list[int] | None = None,
) -> Node:
    """Check a condition tree against the field table and return it as ``Node``."""
    count = _count if _count is not None else [0]
    count[0] += 1
    if count[0] > MAX_NODES:
        raise _err(where, f"a condition has more than {MAX_NODES} nodes")
    if _depth > MAX_DEPTH:
        raise _err(where, f"a condition is nested deeper than {MAX_DEPTH} levels")
    if not isinstance(node, Mapping) or not node:
        raise _err(where, "a condition must be an object such as {all: [...]} or {field: ...}")
    keys = set(node)
    combiners = keys & set(COMBINERS)
    if combiners:
        if len(keys) != 1:
            raise _err(where, f"{sorted(combiners)[0]} cannot have other keys beside it")
        name = sorted(combiners)[0]
        body = node[name]
        if name == "not":
            kid = parse(body, lookup, f"{where}.not", _depth=_depth + 1, _count=count)
            return Node("not", (kid,))
        if not isinstance(body, Sequence) or isinstance(body, str) or not body:
            raise _err(where, f"{name} must be a non-empty list")
        kids = tuple(
            parse(b, lookup, f"{where}.{name}[{i}]", _depth=_depth + 1, _count=count)
            for i, b in enumerate(body)
        )
        return Node(name, kids)
    unknown = sorted(str(k) for k in keys - {"field", *OPERATORS})
    if unknown:
        raise _err(where, f"unknown key: {', '.join(unknown)}")
    name = node.get("field")
    if not isinstance(name, str):
        raise _err(where, "a leaf needs field")
    ops = sorted(keys & set(OPERATORS))
    if len(ops) != 1:
        raise _err(where, f"field {name}: give exactly one operator ({', '.join(OPERATORS)})")
    spec = lookup(name)
    if spec is None:
        raise _err(where, f"unknown field {name}")
    op = ops[0]
    return Node("leaf", (), name, op, _check_value(spec, name, op, node[op], where))


def _check_value(spec: FieldSpec, name: str, op: str, value: Any, where: str) -> Any:
    kind = spec.kind
    if op == "is_true":
        if kind != "bool":
            raise _err(where, f"field {name} is not a yes/no field; is_true does not fit")
        if value is not True:
            raise _err(where, f"field {name}: is_true must be true")
        return True
    if op == "gte":
        if kind == "ordered":
            if value not in (spec.values or ()):
                raise _err(
                    where, f"field {name}: gte must be one of {', '.join(spec.values or ())}"
                )
            return value
        if kind == "int":
            if isinstance(value, bool) or not isinstance(value, int):
                raise _err(where, f"field {name}: gte must be a whole number")
            return value
        raise _err(where, f"field {name}: gte works on ordered and numeric fields only")
    if op == "eq":
        if isinstance(value, (list, dict)):
            raise _err(where, f"field {name}: eq takes one value (use in for a list)")
        items: Sequence[Any] = [value]
    else:
        if not isinstance(value, list) or not value:
            raise _err(where, f"field {name}: in takes a non-empty list")
        items = value
    for v in items:
        if kind == "bool":
            if not isinstance(v, bool):
                raise _err(where, f"field {name}: use true or false")
        elif kind == "int":
            if isinstance(v, bool) or not isinstance(v, int):
                raise _err(where, f"field {name}: use a whole number")
        else:
            if not isinstance(v, str):
                raise _err(where, f"field {name}: use text values")
            if spec.values is not None and v not in spec.values:
                raise _err(where, f"field {name}: {v!r} is not one of {', '.join(spec.values)}")
    return list(items) if op == "in" else value


def _leaf(node: Node, actual: Any, spec: FieldSpec | None) -> bool:
    if actual is None:
        return False
    op, want = node.operator, node.value
    if op == "is_true":
        return actual is True
    if op == "gte":
        if spec is not None and spec.kind == "ordered":
            order = spec.values or ()
            return actual in order and order.index(actual) >= order.index(want)
        return isinstance(actual, int) and not isinstance(actual, bool) and actual >= want
    wants = want if op == "in" else [want]
    if isinstance(actual, tuple):  # a set-valued fact: any value may match
        return any(a in wants for a in actual)
    return actual in wants


def evaluate(node: Node, facts: Mapping[str, Any], lookup: FieldLookup) -> Trace:
    """Evaluate a parsed tree against facts (field name -> value). Deterministic and pure."""
    if node.op == "leaf":
        actual = facts.get(node.field)
        if isinstance(actual, (set, frozenset, list, tuple)):
            actual = tuple(sorted(actual))
        return Trace(
            "leaf",
            _leaf(node, actual, lookup(node.field)),
            (),
            node.field,
            node.operator,
            node.value,
            actual,
        )
    kids = tuple(evaluate(c, facts, lookup) for c in node.children)
    if node.op == "all":
        return Trace("all", all(k.result for k in kids), kids)
    if node.op == "any":
        return Trace("any", any(k.result for k in kids), kids)
    return Trace("not", not kids[0].result, kids)


def support(t: Trace) -> frozenset[str]:
    """The fields that decided this result: for a true ``all`` every child, for a true ``any`` the
    true children, for a false ``all`` the false children, for a false ``any`` every child."""
    if t.op == "leaf":
        return frozenset({t.field})
    if t.op == "not":
        return support(t.children[0])
    if t.op == "all":
        kids = t.children if t.result else tuple(c for c in t.children if not c.result)
    else:
        kids = tuple(c for c in t.children if c.result) if t.result else t.children
    out: set[str] = set()
    for c in kids:
        out |= support(c)
    return frozenset(out)


def render(t: Trace, indent: int = 0) -> list[str]:
    """ASCII lines of a trace, for ``explain``."""
    pad = "  " * indent
    mark = "[x]" if t.result else "[ ]"
    if t.op == "leaf":
        want = "true" if t.operator == "is_true" else repr(t.value)
        seen = "(no value)" if t.actual is None else repr(t.actual)
        return [f"{pad}{mark} {t.field} {t.operator} {want}  seen {seen}"]
    lines = [f"{pad}{mark} {t.op}"]
    for c in t.children:
        lines += render(c, indent + 1)
    return lines

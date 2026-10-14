"""The verifier's stdlib canonical module must match core/canonical.py byte for byte."""

from __future__ import annotations

import random
import uuid
from datetime import UTC, date, datetime, timedelta, timezone
from enum import Enum
from pathlib import Path

import pytest

from supervisor import sandbox
from supervisor.core import canonical as core
from supervisor.evidence import _canonical_stdlib as std
from tests.test_canonical import VECTORS


class Color(Enum):
    RED = "red"
    ONE = 1


def _float_free(value: object) -> bool:
    if isinstance(value, float):
        return False
    if isinstance(value, dict):
        return all(_float_free(v) for v in value.values())
    if isinstance(value, list | tuple):
        return all(_float_free(v) for v in value)
    return True


@pytest.mark.parametrize("value,text,digest", [v for v in VECTORS if _float_free(v[0])])
def test_existing_vectors_match(value: object, text: str, digest: str) -> None:
    assert std.canonical_json(value) == text
    assert std.sha256_hex(value) == digest
    assert std.canonical_bytes(value) == core.canonical_bytes(value)


def test_floats_rejected_by_stdlib_only() -> None:
    with pytest.raises(std.CanonicalError):
        std.canonical_json({"f": 0.1})


_ALPHABET = 'abXY09 _"\\/\n\téệ中\U0001f600'


def _rand_str(rng: random.Random) -> str:
    return "".join(rng.choice(_ALPHABET) for _ in range(rng.randint(0, 8)))


def _rand_value(rng: random.Random, depth: int = 0) -> object:
    kinds = ["none", "bool", "int", "str", "dt", "date", "uuid", "enum"]
    if depth < 3:
        kinds += ["list", "tuple", "dict", "dict"]
    kind = rng.choice(kinds)
    if kind == "none":
        return None
    if kind == "bool":
        return rng.random() < 0.5
    if kind == "int":
        return rng.choice([0, -1, 2**63 - 1, -(2**63), rng.randint(-(10**9), 10**9)])
    if kind == "str":
        return _rand_str(rng)
    if kind == "dt":
        tz = timezone(timedelta(hours=rng.randint(-12, 14)))
        base = datetime(2026, 1, 1, tzinfo=UTC) + timedelta(seconds=rng.randint(0, 10**8))
        return base.replace(microsecond=rng.randint(0, 999999)).astimezone(tz)
    if kind == "date":
        return date(2020, 1, 1) + timedelta(days=rng.randint(0, 3000))
    if kind == "uuid":
        return uuid.UUID(int=rng.getrandbits(128))
    if kind == "enum":
        return rng.choice(list(Color))
    if kind in ("list", "tuple"):
        items = [_rand_value(rng, depth + 1) for _ in range(rng.randint(0, 4))]
        return items if kind == "list" else tuple(items)
    out: dict[str, object] = {}
    for _ in range(rng.randint(0, 5)):
        key = rng.choice([_rand_str(rng), "amount_minor", "x_minor"])
        out[key] = (
            rng.choice([None, rng.randint(-5, 5)])
            if key.endswith("_minor")
            else (_rand_value(rng, depth + 1))
        )
    return out


def test_200_random_structures_identical() -> None:
    rng = random.Random(20261014)
    for i in range(200):
        value = _rand_value(rng)
        assert std.canonical_bytes(value) == core.canonical_bytes(value), i
        assert std.sha256_hex(value) == core.sha256_hex(value), i


@pytest.mark.parametrize(
    "bad",
    [
        {"a_minor": "5"},
        {"a_minor": 1.5},
        datetime(2026, 1, 1),
        {1: "x"},
        2**63,
        b"x",
    ],
)
def test_both_reject_the_same_bad_values(bad: object) -> None:
    with pytest.raises(TypeError):
        core.canonical_json(bad)
    with pytest.raises(TypeError):
        std.canonical_json(bad)


def test_verify_imports_without_pydantic(tmp_path: Path) -> None:
    code = (
        "import sys; sys.modules['pydantic'] = None; "
        "import supervisor.evidence.verify as v; "
        "assert 'pydantic' not in [m for m, x in sys.modules.items() if x is not None]; "
        "assert 'supervisor.core.canonical' not in sys.modules; "
        "print('IMPORT_OK')"
    )
    res = sandbox.run([sandbox.python_executable(), "-c", code], cwd=tmp_path, timeout_s=60)
    assert res.returncode == 0, res.stdout + res.stderr
    assert "IMPORT_OK" in res.stdout

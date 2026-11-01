"""Table-driven tests of the shared helpers in core (code clean-up audit, Step 0)."""

from __future__ import annotations

import datetime as dt
import math
import os
import time
from decimal import Decimal
from pathlib import Path

import pytest

from supervisor.core import filecache
from supervisor.core.csvsafe import csv_cell, write_csv
from supervisor.core.flags import truthy
from supervisor.core.people import is_system_owner, same_person
from supervisor.core.rows import json_value, plain
from supervisor.core.stats import Z95, wilson_bp, wilson_bp_full
from supervisor.core.timeutil import iso_z, parse_utc, parse_utc_strict

UTC = dt.UTC


# ------------------------------------------------------------------------------- flags


@pytest.mark.parametrize(
    ("value", "want"),
    [
        ("1", True),
        ("true", True),
        ("TRUE", True),
        (" True ", True),
        ("0", False),
        ("false", False),
        ("", False),
        ("yes", False),
        ("2", False),
        (1, True),
        (0, False),
        (True, True),
        (False, False),
        (None, False),
        (2, True),
        (0.0, False),
    ],
)
def test_truthy(value, want):
    assert truthy(value) is want


# ------------------------------------------------------------------------------ timeutil

_T = dt.datetime(2026, 10, 30, 8, 0, 5, tzinfo=UTC)


@pytest.mark.parametrize(
    ("value", "want"),
    [
        ("2026-10-30T08:00:05Z", _T),
        ("2026-10-30T08:00:05+00:00", _T),
        ("2026-10-30T15:00:05+07:00", _T),
        ("2026-10-30T08:00:05", _T),
        (_T, _T),
        (_T.replace(tzinfo=None), _T),
        (dt.datetime(2026, 10, 30, 15, 0, 5, tzinfo=dt.timezone(dt.timedelta(hours=7))), _T),
        ("2026-10-30T08:00:05.250000Z", _T.replace(microsecond=250000)),
        ("junk", None),
        ("", None),
        (None, None),
        (12, None),
        (b"2026-10-30", None),
    ],
)
def test_parse_utc(value, want):
    got = parse_utc(value)
    assert got == want
    if got is not None:
        assert got.utcoffset() == dt.timedelta(0)


@pytest.mark.parametrize(
    ("value", "want"),
    [
        ("2026-10-30T08:00:05Z", _T),
        ("2026-10-30T15:00:05+07:00", _T),
        ("2026-10-30T08:00:05", _T),
        (_T, _T),
        (_T.replace(tzinfo=None), _T),
    ],
)
def test_parse_utc_strict_ok(value, want):
    assert parse_utc_strict(value) == want


@pytest.mark.parametrize("value", ["junk", "", None, 12])
def test_parse_utc_strict_raises(value):
    with pytest.raises(ValueError):
        parse_utc_strict(value)


def test_iso_z_second_precision():
    assert iso_z(_T) == "2026-10-30T08:00:05Z"
    assert iso_z(_T.replace(microsecond=999999)) == "2026-10-30T08:00:05Z"
    assert iso_z(_T.replace(tzinfo=None)) == "2026-10-30T08:00:05Z"
    assert iso_z(_T.astimezone(dt.timezone(dt.timedelta(hours=7)))) == "2026-10-30T08:00:05Z"


# -------------------------------------------------------------------------------- csv

_RULE_CASES = [
    ("=1+1", "'=1+1"),
    ("+1", "'+1"),
    ("-1", "'-1"),
    ("@sum", "'@sum"),
    ("\tx", "'\tx"),
    ("\rx", "'\rx"),
    ("plain", "plain"),
    ("a=b", "a=b"),
    ("", ""),
    (None, ""),
    (5, "5"),
    (0, "0"),
    ("  =x", "  =x"),
]


@pytest.mark.parametrize(("value", "want"), _RULE_CASES)
def test_csv_cell(value, want):
    assert csv_cell(value) == want


def test_csv_cell_flatten_controls():
    assert csv_cell("a\nb\x00c\x7f", flatten_controls=True) == "a b c "
    # the formula test is made before the flattening, so a leading tab is still quoted
    assert csv_cell("\t=1", flatten_controls=True) == "' =1"
    assert csv_cell("=1\n2", flatten_controls=True) == "'=1 2"
    assert csv_cell("a\nb") == "a\nb"


def test_write_csv():
    out = write_csv(["a", "b"], [["=x", 1], [None, "ok"]], "\r\n")
    assert out == "a,b\r\n'=x,1\r\n,ok\r\n"
    assert write_csv(["h"], [], "\n") == "h\n"
    assert write_csv(["h"], [["a,b"]]) == 'h\n"a,b"\n'
    assert write_csv(["h"], [["x\ny"]], flatten_controls=True) == "h\nx y\n"


# ------------------------------------------------------------------------------- stats


def _old_copy(k, n, z):
    p = k / n
    denom = 1 + z * z / n
    centre = (p + z * z / (2 * n)) / denom
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / denom
    return max(0, math.floor((centre - half) * 10000)), min(
        10000, math.ceil((centre + half) * 10000)
    )


@pytest.mark.parametrize("k,n", [(0, 1), (1, 1), (7, 7), (0, 570), (5, 10), (40, 40), (3, 97)])
def test_wilson_bp_matches_old_copies(k, n):
    assert wilson_bp(k, n) == _old_copy(k, n, 1.96)
    assert wilson_bp(k, n, Z95) == _old_copy(k, n, 1.959964)
    assert wilson_bp_full(k, n) == _old_copy(k, n, 1.959964)


def test_wilson_bp_known_values():
    assert wilson_bp(40, 40) == (9123, 10000)
    assert wilson_bp_full(7, 7) == (6456, 10000)
    assert all(isinstance(x, int) for x in wilson_bp(5, 10) or ())


def test_wilson_bp_empty():
    assert wilson_bp(0, 0) is None
    assert wilson_bp(1, -1) is None
    assert wilson_bp_full(0, 0) == (0, 10000)


# ------------------------------------------------------------------------------ people


@pytest.mark.parametrize(
    ("a", "b", "want"),
    [
        ("alice", "alice", True),
        ("Alice", "alice", True),
        (" alice ", "ALICE", True),
        ("alice", "bob", False),
        ("", "", False),
        (None, None, False),
        ("alice", None, False),
        (None, "alice", False),
    ],
)
def test_same_person(a, b, want):
    assert same_person(a, b) is want


def test_is_system_owner():
    system = {"owner_user": "Alice"}
    team = [
        {"user_id": "bob", "team_role": "system_owner", "active": "true"},
        {"user_id": "carol", "team_role": "system_owner", "active": "false"},
        {"user_id": "dan", "team_role": "reviewer", "active": True},
        {"user_id": "erin", "team_role": "system_owner"},
    ]
    assert is_system_owner(system, team, "alice")
    assert is_system_owner(system, team, "BOB")
    assert is_system_owner(system, team, "erin")
    assert not is_system_owner(system, team, "carol")
    assert not is_system_owner(system, team, "dan")
    assert not is_system_owner(system, team, "zed")
    assert not is_system_owner(None, [], "alice")
    assert not is_system_owner({"owner_user": None}, [], "")


def test_is_system_owner_exact_keeps_case():
    system = {"owner_user": "Alice"}
    team = [{"user_id": "Bob", "team_role": "system_owner", "active": "1"}]
    assert is_system_owner(system, team, "Alice", exact=True)
    assert not is_system_owner(system, team, "alice", exact=True)
    assert is_system_owner(system, team, "Bob", exact=True)
    assert not is_system_owner(system, team, "bob", exact=True)


# --------------------------------------------------------------------------------- rows


@pytest.mark.parametrize(
    ("value", "want"),
    [
        (None, "D"),
        ('{"a": 1}', {"a": 1}),
        ("[1, 2]", [1, 2]),
        ("not json", "D"),
        ("", "D"),
        ({"a": 1}, {"a": 1}),
        ([1], [1]),
        (5, "D"),
    ],
)
def test_json_value(value, want):
    assert json_value(value, "D") == want


def test_plain_walks_containers():
    when = dt.datetime(2026, 10, 30, 8, 0, 5, 250000, tzinfo=UTC)
    got = plain({"t": when, "d": dt.date(2026, 10, 30), "l": (when, 1), "n": {"x": [when]}})
    assert got["t"] == "2026-10-30T08:00:05.250000Z"
    assert got["d"] == "2026-10-30"
    assert got["l"] == ["2026-10-30T08:00:05.250000Z", 1]
    assert got["n"] == {"x": ["2026-10-30T08:00:05.250000Z"]}
    assert plain(Decimal("1")) == Decimal("1")


# ---------------------------------------------------------------------------- filecache


def test_load_cached_reuses_until_file_changes(tmp_path: Path):
    filecache.clear_cache()
    f = tmp_path / "c.yaml"
    f.write_text("one")
    calls: list[str] = []

    def loader(p: Path) -> str:
        calls.append(p.read_text())
        return p.read_text()

    assert filecache.load_cached(f, loader) == "one"
    assert filecache.load_cached(str(f), loader) == "one"
    assert calls == ["one"]
    f.write_text("two!")  # new size and new mtime
    assert filecache.load_cached(f, loader) == "two!"
    assert calls == ["one", "two!"]
    # same size, new mtime
    f.write_text("tw0!")
    os.utime(f, ns=(time.time_ns() + 5_000_000_000, time.time_ns() + 5_000_000_000))
    assert filecache.load_cached(f, loader) == "tw0!"
    assert len(calls) == 3


def test_load_cached_missing_file_and_loader_error(tmp_path: Path):
    filecache.clear_cache()
    with pytest.raises(OSError):
        filecache.load_cached(tmp_path / "nope", lambda p: p.read_text())
    f = tmp_path / "bad"
    f.write_text("x")
    n = {"calls": 0}

    def boom(p: Path) -> str:
        n["calls"] += 1
        raise ValueError("bad config")

    for _ in range(2):
        with pytest.raises(ValueError):
            filecache.load_cached(f, boom)
    assert n["calls"] == 2  # a failure is not cached


def test_load_cached_keys_by_loader(tmp_path: Path):
    filecache.clear_cache()
    f = tmp_path / "c"
    f.write_text("abc")
    assert filecache.load_cached(f, lambda p: 1) == 1
    assert filecache.load_cached(f, lambda p: 2) == 2

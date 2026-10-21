"""WP31 review follow-ups F11 and F12: path-safe agent ids; a failed write never blocks the next
generate."""

from __future__ import annotations

from typing import Any

import pytest

from supervisor.transparency.harness import Env
from supervisor.transparency.model import TransparencyError, check_agent


@pytest.mark.parametrize(
    "bad",
    ["..", "a..b", "../x", "x/../y", "a/b", "a\\b", ".hidden", "x.", ".", "a b", "", "x" * 65],
)
def test_agent_id_is_path_safe(bad: str) -> None:
    with pytest.raises(TransparencyError):
        check_agent(bad)


@pytest.mark.parametrize("good", ["payments", "credit_prequal", "a.b", "agent:1", "A-1"])
def test_normal_ids_stay_valid(good: str) -> None:
    assert check_agent(good) == good


def test_a_registered_agent_with_a_dotdot_id_never_reaches_the_filesystem(env: Env) -> None:
    for bad in ("..", "a..b"):
        env.add_agent(bad) if bad != ".." else None
        with pytest.raises(TransparencyError):
            env.svc.generate(bad, actor="u", fresh_verify=False)
        with pytest.raises(TransparencyError):
            env.svc.read(bad, "regulator", "json")
    assert not (env.svc._dir("payments", "regulator", 1).parent.parent.parent / "..x").exists()


def test_rows_fail_after_the_chain_record_then_the_next_generate_works(
    env: Env, monkeypatch: pytest.MonkeyPatch
) -> None:
    real = env.svc.tables.append

    def boom(table: str, rows: Any) -> int:
        if table == "transparency_report":
            raise RuntimeError("store down")
        return real(table, rows)

    monkeypatch.setattr(env.svc.tables, "append", boom)
    with pytest.raises(RuntimeError):
        env.svc.generate("payments", ("customer",), actor="u", fresh_verify=False)
    monkeypatch.setattr(env.svc.tables, "append", real)
    assert not env.svc._dir("payments", "customer", 1).exists()  # files removed
    types = [
        r["record_type"]
        for r in env.adapters.tables.query("chain_entry", {"lane": "agent:payments"})
    ]
    assert "transparency_report" in types and "transparency_report_failed" in types
    again = env.svc.generate("payments", ("customer",), actor="u", fresh_verify=False)[0]
    assert again["status"] == "made" and again["version"] == 1
    assert env.svc.read("payments", "customer", "html", "vi")[2]["status"] == "signed"


def test_chain_fails_before_the_rows_then_the_next_generate_works(
    env: Env, monkeypatch: pytest.MonkeyPatch
) -> None:
    sink = env.svc.evidence_sink
    real = sink.record

    def boom(*a: Any, **k: Any) -> str:
        raise RuntimeError("chain down")

    monkeypatch.setattr(sink, "record", boom)
    with pytest.raises(RuntimeError):
        env.svc.generate("payments", ("customer",), actor="u", fresh_verify=False)
    monkeypatch.setattr(sink, "record", real)
    assert env.svc.rows("payments") == [] and not env.svc._dir("payments", "customer", 1).exists()
    again = env.svc.generate("payments", ("customer",), actor="u", fresh_verify=False)[0]
    assert again["status"] == "made" and again["version"] == 1

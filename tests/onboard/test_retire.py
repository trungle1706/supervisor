"""WP19: Onboard Retire stage, end to end on a temp SQLite store."""

from __future__ import annotations

from pathlib import Path

import pytest

from supervisor.cases import SystemActor, build_case_service
from supervisor.config import load_settings
from supervisor.evidence.export import export_chain
from supervisor.evidence.verify import verify_export
from supervisor.onboard.retire import RetireError, retire_agent
from supervisor.wiring import build_runtime, register_agents
from supervisor_agents.common.manifest import load_manifest

ADMIN = "admin.chi"


@pytest.fixture
def runtime(tmp_path: Path):  # noqa: ANN201
    settings = load_settings(sql_backend="sqlite", data_dir=tmp_path / "data")
    rt = build_runtime(settings)
    register_agents(rt, [load_manifest("payments")])
    try:
        yield rt
    finally:
        rt.close()


def _open(rt, ref: str, severity: str = "high") -> dict:  # noqa: ANN001
    return build_case_service(rt).open_case(
        agent_id="payments",
        severity=severity,
        summary="test",
        source_kind="monitor",
        source_ref=ref,
    )


def test_refuses_running_and_unknown(runtime, tmp_path: Path) -> None:  # noqa: ANN001
    with pytest.raises(RetireError, match="pause it first"):
        retire_agent(runtime, "payments", principal=ADMIN, reason="x", out_dir=tmp_path / "o")
    with pytest.raises(RetireError, match="unknown agent"):
        retire_agent(runtime, "nobody", principal=ADMIN, reason="x", out_dir=tmp_path / "o")
    with pytest.raises(RetireError, match="reason"):
        retire_agent(runtime, "payments", principal=ADMIN, reason=" ", out_dir=tmp_path / "o")
    runtime.gateway.states.pause("payments", "reviewer.an")
    with pytest.raises(RetireError, match="not an admin"):
        retire_agent(runtime, "payments", principal="reviewer.an", reason="x", out_dir=tmp_path)


def test_end_to_end(runtime, tmp_path: Path) -> None:  # noqa: ANN001
    c1, c2 = _open(runtime, "m:1"), _open(runtime, "m:2", "medium")
    runtime.gateway.states.pause("payments", "reviewer.an", "incident")
    out = tmp_path / "out"
    res = retire_agent(runtime, "payments", principal=ADMIN, reason="replaced by v2", out_dir=out)
    assert res.changed and res.previous_state == "PAUSED"
    assert sorted(res.cases_closed) == sorted([c1["case_id"], c2["case_id"]])
    assert res.verify_ok and res.pack_path.is_file() and res.pack_path.parent == out

    agent = runtime.adapters.state.get("agent", {"agent_id": "payments"})
    assert (agent["gate_state"], agent["status"]) == ("RETIRED", "retired")

    cases = build_case_service(runtime)
    for cid in res.cases_closed:
        assert cases.get(cid)["status"] == "closed"
        ev = cases.events(cid)[-1]
        assert ev["action"] == "close:retired"
        assert "agent retired: replaced by v2" in ev["comment_masked"]
        assert cases.signoffs(cid) == []  # no sign-off row: agreement metric unaffected

    lane = runtime.adapters.tables.query("chain_entry", {"lane": "agent:payments"})
    last_types = [e["record_type"] for e in sorted(lane, key=lambda r: r["seq"])]
    assert "agent_retired" in last_types
    assert res.chain_head in {e["entry_hash"] for e in lane}

    note = res.note_path.read_text(encoding="utf-8")
    for needle in ("payments", "replaced by v2", res.chain_head, res.pack_path.name, "FILL-ME"):
        assert needle in note
    assert "PAUSED -> RETIRED" in note

    # the chain still verifies offline
    runtime.chain.commit_root(force=True)
    export_chain(runtime.adapters.tables, tmp_path / "exp")
    assert verify_export(tmp_path / "exp").failures == 0

    # the agent is blocked, and a second run is a safe no-op
    r = runtime.gateway.check("payments", "1.0.0", "get_balance", {"account_id": "ACC-1"}, {})
    assert r["allow"] is False
    again = retire_agent(runtime, "payments", principal=ADMIN, reason="again", out_dir=out)
    assert not again.changed and again.cases_closed == []


def test_close_for_retirement_needs_admin_for_users(runtime) -> None:  # noqa: ANN001
    from supervisor.adapters.auth.base import AuthPrincipal
    from supervisor.cases.service import PermissionDenied

    cases = build_case_service(runtime)
    c = _open(runtime, "m:9")
    rev = AuthPrincipal("rev", "user", "dev_header", frozenset({"reviewer"}))
    with pytest.raises(PermissionDenied):
        cases.close_for_retirement(c["case_id"], rev, "x")
    done = cases.close_for_retirement(c["case_id"], SystemActor(), "x")
    assert done["status"] == "closed"


def test_cli_retire_needs_principal_and_reason(capsys: pytest.CaptureFixture[str]) -> None:
    from supervisor.onboard.__main__ import main

    assert main(["--retire", "payments"]) == 1
    assert "[FAIL]" in capsys.readouterr().out

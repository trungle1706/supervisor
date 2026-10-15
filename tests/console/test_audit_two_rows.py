"""M4: two audit rows per mutating action (attempted before, outcome after); no row, no action."""

from __future__ import annotations

from typing import Any

import pytest

from supervisor.adapters.auth.audit import snapshot_hash
from supervisor.config import Settings

from .conftest import Console


def _rows(console: Console) -> list[dict[str, Any]]:
    return console.ctx.tables.query("console_action", order_by=("ts",))


def _case(console: Console) -> dict[str, Any]:
    console.get("/console/")  # intake
    return next(c for c in console.ctx.cases.list_cases() if "PAY-07" in c["summary"])


def _audit_down(console: Console, monkeypatch: pytest.MonkeyPatch) -> None:
    orig = console.ctx.tables.append

    def boom(table: str, rows: Any, *a: Any, **k: Any) -> Any:
        if table == "console_action":
            raise RuntimeError("db down")
        return orig(table, rows, *a, **k)

    monkeypatch.setattr(console.ctx.tables, "append", boom)


def _agent(console: Console) -> str | None:
    return snapshot_hash(console.ctx.state, "agent", "payments")


def test_success_writes_attempted_then_ok_with_one_request_id(console: Console) -> None:
    c = _case(console)
    r = console.post(
        f"/console/cases/{c['case_id']}/comment", {"text": "x", "row_version": c["row_version"]}
    )
    assert r.status_code == 200
    rows = [x for x in _rows(console) if x["permission"] == "case.comment"]
    assert [x["outcome"] for x in rows] == ["attempted", "ok"]
    assert rows[0]["request_id"] == rows[1]["request_id"]
    assert rows[0]["before_hash"] and rows[0]["after_hash"] is None
    assert rows[1]["before_hash"] and rows[1]["after_hash"] != rows[1]["before_hash"]


def test_audit_down_console_case_action_is_not_done(
    console: Console, monkeypatch: pytest.MonkeyPatch
) -> None:
    c = _case(console)
    before = console.ctx.state.get("cases", {"case_id": c["case_id"]})
    _audit_down(console, monkeypatch)
    r = console.post(
        f"/console/cases/{c['case_id']}/comment", {"text": "x", "row_version": c["row_version"]}
    )
    assert r.status_code == 400 and "audit store unavailable" in r.text
    assert console.ctx.state.get("cases", {"case_id": c["case_id"]}) == before


def test_audit_down_console_agent_pause_is_not_done(
    console: Console, monkeypatch: pytest.MonkeyPatch
) -> None:
    before = _agent(console)
    _audit_down(console, monkeypatch)
    r = console.post("/console/agents/payments/pause", {"reason": "t"})
    assert r.status_code == 400 and "the action was not done" in r.text
    assert _agent(console) == before
    r = console.post("/console/intake/run", {})
    assert r.status_code == 400


def test_audit_down_gate_control_is_not_done(
    console: Console, monkeypatch: pytest.MonkeyPatch
) -> None:
    body = {"agent_id": "payments", "reason": "t"}
    admin = {"X-Dev-User": "admin.chi"}
    assert console.client.post("/gate/quarantine", json=body, headers=admin).status_code == 200
    quarantined = _agent(console)
    _audit_down(console, monkeypatch)
    r = console.client.post("/gate/release", json=body, headers=admin)
    assert r.status_code == 400 and "audit store unavailable" in r.json()["error"]
    assert _agent(console) == quarantined  # still quarantined


def test_gate_control_writes_two_rows(console: Console) -> None:
    body = {"agent_id": "payments", "reason": "t"}
    r = console.client.post("/gate/pause", json=body, headers={"X-Dev-User": "reviewer.an"})
    assert r.status_code == 200
    rows = [x for x in _rows(console) if x["permission"] == "agent.pause"]
    assert [x["outcome"] for x in rows] == ["attempted", "ok"]
    assert rows[0]["request_id"] == rows[1]["request_id"]


def test_denied_403_writes_one_denied_row(console: Console) -> None:
    r = console.post("/console/agents/payments/quarantine", {"reason": "t"}, user="reviewer.an")
    assert r.status_code == 403
    assert [x["outcome"] for x in _rows(console)] == ["denied"]


def test_unknown_dev_user_is_audited_as_unverified(console: Console) -> None:
    c = _case(console)
    r = console.post(f"/console/cases/{c['case_id']}/verify", {}, user="nobody")
    assert r.status_code == 400
    (row,) = _rows(console)
    assert row["actor_kind"] == "unverified" and row["actor"] == "unverified:nobody"
    assert row["outcome"] == "denied" and row["detail"] == "identity_unknown"
    assert row["auth_method"] == "dev_header" and row["permission"] == "case.verify"


def test_audit_pack_includes_both_rows(console: Console, tmp_path: Any) -> None:
    import json
    import zipfile
    from pathlib import Path

    assert console.post("/console/agents/payments/pause", {"reason": "t"}).status_code == 200
    assert console.post("/console/export", {}, user="auditor.dung").status_code == 200
    zips = sorted(Path(console.ctx.settings.console_export_dir).glob("audit-pack-*.zip"))
    with zipfile.ZipFile(zips[0]) as zf:
        zf.extractall(tmp_path)
    lines = (tmp_path / zips[0].stem / "console_action.jsonl").read_text("utf-8").splitlines()
    outcomes = [json.loads(x)["outcome"] for x in lines if "agent.pause" in x]
    assert outcomes == ["attempted", "ok"]


def test_audit_off_refused_outside_dev_mode() -> None:
    for mode in ("laptop", "databricks_app"):
        with pytest.raises(ValueError, match="CONSOLE_AUDIT_ENABLED=0"):
            Settings(
                _env_file=None,
                console_audit_enabled=False,
                supervisor_mode=mode,
                databricks_host="https://x.cloud.databricks.com",
            )
    s = Settings(_env_file=None, console_audit_enabled=False, supervisor_mode="dev")
    assert s.console_audit_enabled is False


def test_runtime_flag_is_ignored_outside_dev_mode(
    console: Console, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(console.ctx.settings, "console_audit_enabled", False)  # laptop mode
    assert console.post("/console/agents/payments/pause", {"reason": "t"}).status_code == 200
    assert [x["outcome"] for x in _rows(console)] == ["attempted", "ok"]

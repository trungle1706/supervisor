"""WP18 backup, restore, export-delta (SQLite; Databricks through the recorded fake)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from supervisor import cli
from supervisor.adapters.factory import build_adapters
from supervisor.adapters.sql.databricks_fake import FakeStatementExecution
from supervisor.adapters.sql.databricks_rest import DatabricksRestExecutor
from supervisor.config import Settings, load_settings
from supervisor.core.schema import load_model
from supervisor.evidence.chain import ChainWriter
from supervisor.evidence.signer import build_signer
from supervisor.jobs.bootstrap_schema import run as bootstrap_run
from supervisor.ops import backup as B


def seed(settings: Settings, n: int = 7) -> None:
    a = build_adapters(settings)
    try:
        bootstrap_run(settings, a)
        w = ChainWriter(a.tables, a.clock, build_signer(settings), root_every_n=3)
        for i in range(n):
            w.record("note", f"n{i}", {"agent_id": "payments", "i": i})
        w.close()
    finally:
        a.close()


@pytest.fixture
def cfg(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Settings:
    monkeypatch.setenv("SQL_BACKEND", "sqlite")
    monkeypatch.setenv("LLM_BASE_URL", "")
    monkeypatch.setenv("DATA_DIR", str(tmp_path / "data"))
    s = load_settings(data_dir=tmp_path / "data", sql_backend="sqlite", llm_base_url="")
    seed(s)
    return s


def counts(settings: Settings) -> dict[str, int]:
    a = build_adapters(settings)
    try:
        return B.table_counts(a)
    finally:
        a.close()


def run(capsys: pytest.CaptureFixture[str], *argv: str) -> tuple[int, str]:
    code = cli.main(list(argv))
    out = capsys.readouterr().out
    assert out.isascii()
    return code, out


def test_roundtrip_backup_wipe_restore(cfg: Settings, tmp_path: Path, capsys) -> None:
    before = counts(cfg)
    assert before["chain_entry"] >= 7
    bdir = tmp_path / "bk"
    code, out = run(capsys, "backup", "--out", str(bdir))
    assert code == 0 and "[OK] database copy" in out and "signing key not included" in out
    m = json.loads((bdir / "manifest.json").read_text())
    assert m["signing_key_included"] is False and "NOT in this backup" in m["signing_key_note"]
    assert m["table_counts"] == before
    assert m["db_sha256"] == B.sha256_file(bdir / "supervisor.db")
    assert any(h["lane"] == "root" for h in m["chain_lane_heads"])
    assert not (bdir / B.KEY_NAME).exists()
    # modify the live store, then restore
    a = build_adapters(cfg)
    w = ChainWriter(a.tables, a.clock, build_signer(cfg))
    w.record("note", "extra", {"agent_id": "payments"})
    w.close()
    a.close()
    assert counts(cfg) != before
    code, out = run(capsys, "restore", "--from", str(bdir))
    assert code == 1 and "[FAIL]" in out and "exists" in out
    code, out = run(capsys, "restore", "--from", str(bdir), "--force")
    assert code == 0 and "[OK] evidence chain verifies" in out
    assert counts(cfg) == before
    aside = list(cfg.sqlite_path.parent.glob("*.pre-restore-*"))  # type: ignore[union-attr]
    assert len(aside) == 1


def test_include_key_and_restore_key(cfg: Settings, tmp_path: Path, capsys) -> None:
    bdir = tmp_path / "bk"
    code, out = run(capsys, "backup", "--out", str(bdir), "--include-key")
    assert code == 0 and "[WARN]" in out and (bdir / B.KEY_NAME).is_file()
    assert json.loads((bdir / "manifest.json").read_text())["signing_key_included"] is True
    cfg.signer_key_path.unlink()  # type: ignore[union-attr]
    cfg.sqlite_path.unlink()  # type: ignore[union-attr]
    code, out = run(capsys, "restore", "--from", str(bdir))
    assert code == 0 and "signing key restored" in out
    assert cfg.signer_key_path.is_file()  # type: ignore[union-attr]


def test_restore_refuses_sha_mismatch_and_newer_schema(cfg: Settings, tmp_path: Path) -> None:
    bdir = tmp_path / "bk"
    B.backup(cfg, bdir)
    target = tmp_path / "other.db"
    s2 = cfg.model_copy(update={"sqlite_path": target})
    mpath = bdir / "manifest.json"
    m = json.loads(mpath.read_text())
    m["schema_version"] = load_model().version + 1
    mpath.write_text(json.dumps(m))
    with pytest.raises(B.BackupError, match="newer"):
        B.restore(s2, bdir)
    m["schema_version"] = load_model().version
    mpath.write_text(json.dumps(m))
    with (bdir / "supervisor.db").open("ab") as fh:
        fh.write(b"x")
    with pytest.raises(B.BackupError, match="sha256 mismatch"):
        B.restore(s2, bdir)
    assert not target.exists()


def test_restore_to_new_data_dir_and_verify(cfg: Settings, tmp_path: Path) -> None:
    bdir = tmp_path / "bk"
    B.backup(cfg, bdir, include_key=True)
    s2 = load_settings(data_dir=tmp_path / "dr", sql_backend="sqlite", llm_base_url="")
    r = B.restore(s2, bdir)
    assert r["verify_ok"] and r["key_restored"]
    assert counts(s2) == counts(cfg)


def test_backup_refused_in_app_mode(tmp_path: Path, capsys, monkeypatch) -> None:
    monkeypatch.setenv("SQL_BACKEND", "databricks_rest")
    code, out = run(capsys, "backup", "--out", str(tmp_path / "x"))
    assert code == 1
    assert "[FAIL] backup is for SQLite mode; use export-delta" in out


def test_backup_nonempty_dir_refused(cfg: Settings, tmp_path: Path) -> None:
    d = tmp_path / "bk"
    d.mkdir()
    (d / "f").write_text("x")
    with pytest.raises(B.BackupError, match="not empty"):
        B.backup(cfg, d)


def test_export_delta_sqlite(cfg: Settings, tmp_path: Path, capsys) -> None:
    out_dir = tmp_path / "ex"
    code, _ = run(capsys, "export-delta", "--out", str(out_dir))
    assert code == 0
    m = json.loads((out_dir / "manifest.json").read_text())
    model = load_model()
    want = counts(cfg)
    assert set(m["tables"]) == set(model.tables)
    for name, info in m["tables"].items():
        lines = (out_dir / f"{name}.jsonl").read_text(encoding="utf-8").splitlines()
        assert len(lines) == info["rows"] == want[name]
        assert info["sha256"] == B.sha256_file(out_dir / f"{name}.jsonl")
    assert m["workspace_host"] == "FILL-ME-host"
    assert "token" not in json.dumps(m).lower()
    sub = tmp_path / "ex2"
    code, _ = run(capsys, "export-delta", "--out", str(sub), "--tables", "chain_entry,anchor")
    assert code == 0
    assert sorted(p.name for p in sub.glob("*.jsonl")) == ["anchor.jsonl", "chain_entry.jsonl"]
    code, _ = run(capsys, "export-delta", "--out", str(tmp_path / "ex3"), "--tables", "nope")
    assert code == 1


def test_export_delta_app_mode_fake(tmp_path: Path, monkeypatch) -> None:
    types = load_model().table("chain_entry").types
    cols = [(c, "LONG" if t == "int" else "STRING") for c, t in types.items()]
    row = [
        "root",
        "0",
        "2026-10-14T02:00:00.000000Z",
        "root_commit",
        "r",
        "h",
        "p",
        "e",
        "w",
        "dev",
    ]
    fake = FakeStatementExecution().add_rows(cols, [row])
    ex = DatabricksRestExecutor(
        fake, warehouse_id="wh", catalog="cat", schema="sch", sleep=lambda s: None
    )
    settings = load_settings(
        sql_backend="databricks_rest",
        databricks_host="https://adb-1.azuredatabricks.net",
        databricks_warehouse_id="wh",
        databricks_catalog="cat",
        databricks_schema="sch",
    )
    monkeypatch.setattr("supervisor.adapters.factory.build_sql_executor", lambda s: ex)
    out_dir = tmp_path / "ex"
    m = B.export_delta(settings, out_dir, tables=["chain_entry"])
    assert m["tables"]["chain_entry"]["rows"] == 1
    assert m["workspace_host"] == "https://adb-1.azuredatabricks.net"
    rec: dict[str, Any] = json.loads((out_dir / "chain_entry.jsonl").read_text().splitlines()[0])
    assert rec["seq"] == 0 and rec["ts"].startswith("2026-10-14T02:00:00")
    sqls = [c.kwargs.get("statement", "") for c in fake.calls if c.method == "execute_statement"]
    assert len(sqls) == 1 and sqls[0].startswith("SELECT ") and "chain_entry" in sqls[0]

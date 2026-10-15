"""WP18 support bundle: no secret and no PII leaves the machine; works with and without a store."""

from __future__ import annotations

import json
import zipfile
from pathlib import Path

import pytest

from supervisor import cli
from supervisor.adapters.factory import build_adapters
from supervisor.config import load_settings
from supervisor.evidence.chain import ChainWriter
from supervisor.evidence.signer import build_signer
from supervisor.jobs.bootstrap_schema import run as bootstrap_run

SECRETS = {
    "LLM_API_KEY": "fake-llm-credential-9f8e7d6c5b4a",
    "MASK_HMAC_KEY": "maskhmac-SECRET-1a2b3c4d5e6f",
    "DATABRICKS_CLIENT_SECRET": "dbx-client-SECRET-77aa88bb99cc",
}
PII = ["0912345678", "079123456789", "nguyen.van.a@example.com", "1903456789012"]
LOG_LINES = [
    "2026-10-15 10:00:00 INFO start",
    "customer phone 0912345678 asked about balance",
    "CCCD 079123456789 verified",
    "mail nguyen.van.a@example.com sent",
    "so tai khoan: 1903456789012 debited",
    f"auth failed with key {SECRETS['LLM_API_KEY']}",
    "api_key=abcdef1234567890SECRETvalue",
]


@pytest.fixture
def env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    for k, v in SECRETS.items():
        monkeypatch.setenv(k, v)
    monkeypatch.setenv("DATABRICKS_CLIENT_ID", "client-id-7788")
    monkeypatch.setenv("SQL_BACKEND", "sqlite")
    monkeypatch.setenv("LLM_BASE_URL", "")
    monkeypatch.setenv("DATA_DIR", str(tmp_path / "data"))
    log = tmp_path / "app.log"
    old = tmp_path / "app.log.1"
    old.write_text("\n".join(LOG_LINES[:3]) + "\n", encoding="utf-8")
    log.write_text("\n".join(LOG_LINES[3:]) + "\n", encoding="utf-8")
    monkeypatch.setenv("LOG_FILE", str(log))
    return tmp_path


def seed_store() -> None:
    s = load_settings()
    a = build_adapters(s)
    try:
        bootstrap_run(s, a)
        w = ChainWriter(a.tables, a.clock, build_signer(s), root_every_n=2)
        for i in range(3):
            w.record("note", f"n{i}", {"agent_id": "payments", "i": i})
        w.close()
    finally:
        a.close()


def all_text(out: Path) -> str:
    parts = [p.read_text(encoding="utf-8") for p in sorted(out.iterdir()) if p.suffix != ".zip"]
    zips = list(out.glob("support-bundle-*.zip"))
    assert len(zips) == 1
    with zipfile.ZipFile(zips[0]) as zf:
        assert zf.testzip() is None
        for name in zf.namelist():
            parts.append(zf.read(name).decode("utf-8"))
        names = set(zf.namelist())
    assert {"settings.json", "preflight.txt", "schema.json", "chain.json", "logs.txt"} <= names
    assert {"env.json", "manifest.json"} <= names
    return "\n".join(parts)


def check_clean(out: Path) -> str:
    blob = all_text(out)
    for v in SECRETS.values():
        assert v not in blob
    for v in PII:
        assert v not in blob
    assert "abcdef1234567890SECRETvalue" not in blob
    assert "client-id-7788" not in blob
    return blob


def test_bundle_empty_store(env: Path, capsys: pytest.CaptureFixture[str]) -> None:
    out = env / "bundle"
    assert cli.main(["support-bundle", "--out", str(out)]) == 0
    text = capsys.readouterr().out
    assert text.isascii() and "[OK] settings.json" in text and "[OK] wrote" in text
    check_clean(out)
    assert "not reachable" in json.loads((out / "schema.json").read_text())["store"]
    assert json.loads((out / "chain.json").read_text())["lanes"] == []
    settings = json.loads((out / "settings.json").read_text())
    assert settings["llm_api_key"] == "***set***"
    assert settings["mask_hmac_key"] == "***set***"
    assert settings["databricks_client_secret"] == "***set***"
    assert settings["databricks_client_id"] == "***set***"
    assert not (env / "data" / "supervisor.db").exists()  # the bundle must not create the store


def test_bundle_seeded_store_logs_masked(env: Path) -> None:
    seed_store()
    out = env / "bundle"
    assert cli.main(["support-bundle", "--out", str(out), "--log-lines", "50"]) == 0
    check_clean(out)
    logs = (out / "logs.txt").read_text(encoding="utf-8")
    assert "start" in logs and "balance" in logs  # rotated file lines are included
    assert "***redacted***" in logs
    schema = json.loads((out / "schema.json").read_text())
    assert schema["store"] == "ok" and schema["schema_version_rows"]
    assert schema["model_hash"]
    lanes = json.loads((out / "chain.json").read_text())["lanes"]
    assert {x["lane"] for x in lanes} >= {"root"} and all("entry_hash" in x for x in lanes)
    assert "payload" not in json.dumps(lanes)
    manifest = json.loads((out / "manifest.json").read_text())
    assert set(manifest["files"]) >= {"settings.json", "logs.txt", "env.json"}
    env_json = json.loads((out / "env.json").read_text())
    assert env_json["backend"] == "sqlite" and "optional_extras_importable" in env_json
    pre = (out / "preflight.txt").read_text()
    assert pre.isascii() and "network checks" in pre


def test_log_line_limit_and_no_log_file(env: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    out = env / "b1"
    assert cli.main(["support-bundle", "--out", str(out), "--log-lines", "2"]) == 0
    assert len((out / "logs.txt").read_text().strip().splitlines()) == 2
    monkeypatch.delenv("LOG_FILE")
    out2 = env / "b2"
    assert cli.main(["support-bundle", "--out", str(out2)]) == 0
    assert "LOG_FILE not set" in (out2 / "logs.txt").read_text()


def test_non_empty_dir_needs_force(env: Path) -> None:
    out = env / "b"
    out.mkdir()
    (out / "x.txt").write_text("x")
    assert cli.main(["support-bundle", "--out", str(out)]) == 1
    assert cli.main(["support-bundle", "--out", str(out), "--force"]) == 0


def test_url_query_stripped(env: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LLM_BASE_URL", "http://127.0.0.1:11434/v1?api-key=ABCD1234&x=1")
    out = env / "b"
    assert cli.main(["support-bundle", "--out", str(out)]) == 0
    s = json.loads((out / "settings.json").read_text())
    assert s["llm_base_url"] == "http://127.0.0.1:11434/v1"
    assert "ABCD1234" not in all_text(out)

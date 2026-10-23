"""Schema-level validation of databricks.yml and app.yaml.

``databricks bundle validate`` needs the CLI and a workspace; it runs on the bank laptop
(docs/RUNBOOK.md section 7). These checks catch the mistakes we can see from here.
"""

from __future__ import annotations

import re
from typing import Any

import yaml

from tests.conftest import REPO_ROOT
from tests.test_no_secrets import PATTERNS

BUNDLE = REPO_ROOT / "databricks.yml"
APP = REPO_ROOT / "app.yaml"
APP_NAME = re.compile(r"^[a-z0-9-]+$")  # after FILL-ME is replaced (lowercase)
HEX_ID = re.compile(r"\b[0-9a-f]{16}\b")  # SQL warehouse ids look like this


def _load(path: Any) -> dict[str, Any]:
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    assert isinstance(data, dict)
    return data


def _app(bundle: dict[str, Any]) -> dict[str, Any]:
    return bundle["resources"]["apps"]["supervisor"]


def test_bundle_parses_and_has_required_keys() -> None:
    b = _load(BUNDLE)
    assert b["bundle"]["name"] == "supervisor"
    app = _app(b)
    assert app["source_code_path"] == "./"
    assert app["user_api_scopes"] == ["sql"]
    res = {r["name"]: r for r in app["resources"]}
    assert set(res) == {"sql-warehouse", "llm-endpoint"}
    assert res["sql-warehouse"]["sql_warehouse"]["permission"] == "CAN_USE"
    assert res["sql-warehouse"]["sql_warehouse"]["id"].startswith("FILL-ME")
    assert res["llm-endpoint"]["serving_endpoint"]["permission"] == "CAN_QUERY"
    assert res["llm-endpoint"]["serving_endpoint"]["name"].startswith("FILL-ME")


def test_bundle_targets_dev_default_and_prod_distinct_names() -> None:
    b = _load(BUNDLE)
    dev, prod = b["targets"]["dev"], b["targets"]["prod"]
    assert dev["mode"] == "development" and dev["default"] is True
    assert prod["mode"] == "production"
    for t in (dev, prod):
        assert t["workspace"]["host"] == "https://FILL-ME-workspace-host"
    dev_name = dev["resources"]["apps"]["supervisor"]["name"]
    prod_name = prod["resources"]["apps"]["supervisor"]["name"]
    assert dev_name != prod_name
    for name in (dev_name, prod_name, _app(b)["name"]):
        assert name.endswith("FILL-ME-username")
        filled = name.replace("FILL-ME-username", "user01")
        assert APP_NAME.match(filled) and len(filled) <= 30, name


def test_bundle_has_no_variables_or_secret_scopes() -> None:
    lines = BUNDLE.read_text(encoding="utf-8").splitlines()
    text = "\n".join(line for line in lines if not line.lstrip().startswith("#"))
    b = _load(BUNDLE)
    assert "variables" not in b
    assert "${var." not in text and "--var" not in text
    assert "secret_scope" not in text and "secret:" not in text
    assert "jobs:" not in text and "model_serving_endpoints" not in text


def test_bundle_sync_excludes() -> None:
    excl = set(_load(BUNDLE)["sync"]["exclude"])
    for item in ("/.venv", "/data/local", "/tests", "/docs/handoff", "*.db", "/.env"):
        assert item in excl, item


def _gitignore_match(pattern: str, rel: str) -> bool:
    """Small gitignore emulation: a leading / anchors to the root, else any depth."""
    from fnmatch import fnmatch

    pat = pattern.rstrip("/")
    parts = rel.split("/")
    if pat.startswith("/"):
        pat = pat[1:]
        if "/" not in pat:
            # Observed live (2026-10-23): the Databricks CLI dropped src/supervisor/data for
            # the pattern `/data`. A single-segment pattern matches at any depth, slash or not.
            return any(fnmatch(p, pat) for p in parts)
        return any(fnmatch("/".join(parts[: i + 1]), pat) for i in range(len(parts)))
    if pat.startswith("**/"):
        pat = pat[3:]
    if "/" in pat:
        return any(fnmatch("/".join(parts[i:]), pat + "*") for i in range(len(parts)))
    return any(fnmatch(p, pat) for p in parts)


def test_bundle_sync_keeps_every_source_file() -> None:
    """A bare name like `data` would also drop src/supervisor/data/ (ImportError on the App)."""
    excl = _load(BUNDLE)["sync"]["exclude"]
    needed = [
        p.relative_to(REPO_ROOT).as_posix()
        for top in ("src", "schema", "policies", "agents")
        if (REPO_ROOT / top).exists()
        for p in (REPO_ROOT / top).rglob("*")
        if p.is_file() and "__pycache__" not in p.parts and not p.name.endswith(".pyc")
    ]
    needed += ["app.yaml", "requirements.txt", "databricks.yml"]
    assert "src/supervisor/data/wordlists.py" in needed
    dropped = [f for f in needed for pat in excl if _gitignore_match(pat, f)]
    assert dropped == [], dropped[:10]
    assert _gitignore_match("data", "src/supervisor/data/wordlists.py")  # emulation works
    assert _gitignore_match("/tests", "tests/x.py")
    assert _gitignore_match("/data", "src/supervisor/data/wordlists.py")  # the live CLI did
    assert not _gitignore_match("/data/local", "src/supervisor/data/wordlists.py")


def test_app_yaml_command_and_env() -> None:
    a = _load(APP)
    assert a["command"] == [
        "python",
        "-m",
        "uvicorn",
        "supervisor.app:app",
        "--host",
        "0.0.0.0",  # noqa: S104 - the App platform requires 0.0.0.0
        "--port",
        "8000",
        "--workers",
        "1",
    ]
    env = {e["name"]: e for e in a["env"]}
    assert env["PYTHONPATH"]["value"] == "src"
    assert env["SUPERVISOR_MODE"]["value"] == "databricks_app"
    assert env["SSL_OS_TRUSTSTORE"]["value"] == "0"
    assert env["SCHEDULER_ENABLED"]["value"] == "1"
    for name in ("DATA_DIR", "SPOOL_DIR", "ANCHOR_PATH"):
        assert env[name]["value"].startswith("/Volumes/FILL-ME-catalog/"), name
    assert env["LLM_ENDPOINT"] == {"name": "LLM_ENDPOINT", "valueFrom": "llm-endpoint"}
    assert env["DATABRICKS_WAREHOUSE_ID"] == {
        "name": "DATABRICKS_WAREHOUSE_ID",
        "valueFrom": "sql-warehouse",
    }
    # valueFrom names must be bundle resource names
    bound = {r["name"] for r in _app(_load(BUNDLE))["resources"]}
    assert {e["valueFrom"] for e in a["env"] if "valueFrom" in e} <= bound
    # the platform injects these; the file must not set them
    for name in ("DATABRICKS_TOKEN", "DATABRICKS_CLIENT_SECRET", "DATABRICKS_HOST", "LLM_BASE_URL"):
        assert name not in env, name
    assert "uv run" not in APP.read_text(encoding="utf-8").replace("never uv run", "")


def test_no_real_ids_in_deploy_files() -> None:
    for path in (BUNDLE, APP):
        text = path.read_text(encoding="utf-8")
        assert "FILL-ME" in text
        for name, pat in PATTERNS.items():
            assert not pat.search(text), f"{path.name}: {name}"
        assert not HEX_ID.search(text), f"{path.name}: looks like a warehouse id"
        assert ".cloud.databricks.com" not in text and "nexus" not in text.lower()


def test_app_env_loads_as_settings(monkeypatch: Any, tmp_path: Any) -> None:
    """The env of app.yaml (FILL-ME values filled) plus the injected SP gives valid Settings."""
    from supervisor.config import load_settings

    for e in _load(APP)["env"]:
        value = (
            e.get("value")
            or {"sql-warehouse": "wh01", "llm-endpoint": "my-endpoint"}[e["valueFrom"]]
        )
        value = value.replace("FILL-ME-catalog", "cat").replace("FILL-ME-schema", "sch")
        value = value.replace("FILL-ME-volume", "vol")
        monkeypatch.setenv(e["name"], value)
    monkeypatch.setenv("DATABRICKS_HOST", "example-workspace.invalid")
    monkeypatch.setenv("DATABRICKS_CLIENT_ID", "sp-client-id")
    monkeypatch.setenv("DATABRICKS_CLIENT_SECRET", "sp-secret-value")
    s = load_settings()
    assert s.supervisor_mode == "databricks_app"
    assert s.effective_sql_backend == "databricks_rest"
    assert s.databricks_auth_kind == "service_principal"
    assert s.databricks_host == "https://example-workspace.invalid"
    assert s.llm_base_url == "https://example-workspace.invalid/serving-endpoints"
    assert s.llm_model == "my-endpoint" and s.llm_uses_workspace_auth
    assert str(s.recorder_spool_dir) == "/Volumes/cat/sch/vol/supervisor/spool"
    # this host has no /Volumes mount: DATA_DIR falls back to the container disk, loudly
    assert s.data_dir_requested == "/Volumes/cat/sch/vol/supervisor/data"
    assert not str(s.data_dir).startswith("/Volumes") and s.data_dir.is_absolute()
    # the signing key lives on the Volume (Files API), not on the container disk
    assert s.signer_kind == "uc_volume"
    assert str(s.signer_key_path) == "/Volumes/cat/sch/vol/supervisor/keys/evidence_ed25519.pem"
    assert s.anchor_kind == "uc_volume"
    assert "sp-secret-value" not in repr(s) and "sp-secret-value" not in s.describe_target()

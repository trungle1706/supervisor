"""WP-P1: the deploy package files agree with the code (env names, flags, docs, sweep)."""

from __future__ import annotations

import re
from pathlib import Path

import pytest
import yaml

from supervisor import release
from supervisor.config import Settings, load_settings
from tests.conftest import REPO_ROOT

PHASE45_FLAGS = (
    "GOVERNANCE_ENABLED",
    "CONSOLE_SYSTEMS_ENABLED",
    "CONSOLE_NAV_V3",
    "GOVERNANCE_ACTIONS_ENABLED",
    "GUARDIAN_BINDINGS_ENABLED",
    "MCP_SERVER_ENABLED",
    "INVENTORY_SCAN_V2",
    "INVENTORY_AUTOREGISTER",
    "WEBHOOKS_ENABLED",
    "CLASSIFIER_AI_PREFILL",
    "DOCUMENT_INTAKE_ENABLED",
    "URL_FETCH_ENABLED",
    "URL_FETCH_ALLOWLIST",
    "GUARD_MODEL_ADAPTER",
    "DETECTORS_ENABLED",
)
NAME = re.compile(r"^(?:#\s*)?([A-Z][A-Z0-9_]{2,})=(.*)$")


def known_env_names() -> set[str]:
    names = set()
    for key, field in Settings.model_fields.items():
        names.add(key.upper())
        alias = field.validation_alias
        if isinstance(alias, str):
            names.add(alias.upper())
        elif alias is not None and hasattr(alias, "choices"):
            names.update(str(c).upper() for c in alias.choices)
    return names


def env_lines(path: Path) -> list[tuple[str, str, bool]]:
    """(name, value, active) for every NAME=value line, commented ones included."""
    out = []
    for line in path.read_text(encoding="utf-8").splitlines():
        m = NAME.match(line.strip())
        if m:
            out.append((m.group(1), m.group(2).strip(), not line.lstrip().startswith("#")))
    return out


def test_env_laptop_example_names_are_settings() -> None:
    names = {n for n, _v, _a in env_lines(REPO_ROOT / ".env.laptop.example")}
    unknown = sorted(names - known_env_names())
    assert unknown == [], f"not a Settings field (a typo is silently ignored): {unknown}"
    for flag in PHASE45_FLAGS:
        assert flag in names, flag


def test_env_laptop_example_loads_and_turns_the_story_on(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    for name, value, active in env_lines(REPO_ROOT / ".env.laptop.example"):
        if active:
            monkeypatch.setenv(name, value)
    monkeypatch.setenv("DATA_DIR", str(tmp_path / "d"))
    s = load_settings()
    assert s.governance_enabled and s.console_systems_enabled and s.console_nav_v3
    assert s.mcp_server_enabled and s.document_intake_enabled and s.detectors_enabled
    # the risky or unfinished things stay off in the laptop file
    assert not (s.inventory_scan_v2 or s.inventory_autoregister or s.url_fetch_enabled)
    assert not (s.webhooks_enabled or s.classifier_ai_prefill or s.guard_model_fail_closed_approved)
    assert s.guard_model_url == "" and s.llm_base_url == ""


def test_env_laptop_example_has_placeholders_and_no_secret_assignment() -> None:
    text = (REPO_ROOT / ".env.laptop.example").read_text(encoding="utf-8")
    assert "FILL-ME" in text
    assert not re.search(r"^DATABRICKS_TOKEN\s*=", text, re.M)
    for name, value, active in env_lines(REPO_ROOT / ".env.laptop.example"):
        if name.endswith(("_KEY", "_SECRET")) and active:
            assert value.startswith("FILL-ME") or value == "", name


def test_app_yaml_phase45_env_names_are_settings_and_off_by_default() -> None:
    doc = yaml.safe_load((REPO_ROOT / "app.yaml").read_text(encoding="utf-8"))
    env = {e["name"]: e.get("value") for e in doc["env"]}
    assert doc["command"][:3] == ["python", "-m", "uvicorn"]
    assert env["PYTHONPATH"] == "src"
    skip = {"PYTHONPATH", "DATABRICKS_WAREHOUSE_ID", "LLM_ENDPOINT"}
    unknown = sorted(n for n in env if n not in skip and n not in known_env_names())
    assert unknown == [], unknown
    commented = {n for n, _v, a in env_lines_yaml() if not a}
    assert {"GUARD_MODEL_URL", "GUARD_MODEL_NAME", "GUARD_MODEL_VERSION"} <= commented
    assert {"GUARD_MODEL_URL", "GUARD_MODEL_NAME", "GUARD_MODEL_VERSION"}.isdisjoint(env)
    assert env["INVENTORY_SCAN_V2"] == "0" and env["INVENTORY_AUTOREGISTER"] == "0"
    assert env["URL_FETCH_ENABLED"] == "0" and env["GUARD_MODEL_FAIL_CLOSED_APPROVED"] == "0"
    for flag in PHASE45_FLAGS:
        assert flag in env, flag
    assert "DATABRICKS_TOKEN" not in env
    assert "FILL-ME" in env["INVENTORY_SCAN_SCHEMAS"]


def env_lines_yaml() -> list[tuple[str, str, bool]]:
    out = []
    for line in (REPO_ROOT / "app.yaml").read_text(encoding="utf-8").splitlines():
        m = re.match(r"^\s*(#\s*)?-\s*name:\s*([A-Z][A-Z0-9_]+)\s*$", line)
        if m:
            out.append((m.group(2), "", m.group(1) is None))
    return out


def test_databricks_yml_stays_valid_and_has_no_variables() -> None:
    text = (REPO_ROOT / "databricks.yml").read_text(encoding="utf-8")
    doc = yaml.safe_load(text)
    res = doc["resources"]["apps"]["supervisor"]["resources"]
    assert [r["name"] for r in res] == ["sql-warehouse", "llm-endpoint"]
    assert "guard-model-endpoint" in text  # present, commented out
    assert "variables:" not in text and "secret_scope" not in text and "${var." not in text


def test_requirements_include_the_documents_extra() -> None:
    text = (REPO_ROOT / "requirements.txt").read_text(encoding="utf-8")
    assert re.search(r"^pypdf==", text, re.M)
    assert "--extra documents" in text


def test_leak_sweep_allows_the_laptop_env_example_only() -> None:
    top = release.TOP
    assert release.sweep_paths([f"{top}/.env.laptop.example", f"{top}/.env.example"]) == []
    assert release.sweep_paths([f"{top}/.env"]) != []
    assert release.sweep_paths([f"{top}/.env.local"]) != []
    assert release.sweep_paths([f"{top}/.env.laptop"]) != []


def test_launch_docs_follow_the_rules() -> None:
    laptop = (REPO_ROOT / "docs/deploy/LAUNCH_LAPTOP.md").read_text(encoding="utf-8")
    dbx = (REPO_ROOT / "docs/deploy/LAUNCH_DATABRICKS.md").read_text(encoding="utf-8")
    for text in (laptop, dbx):
        for line in text.splitlines():
            if "DATABRICKS_TOKEN" in line:  # only as a prohibition
                assert re.search(r"never|refuses|remove", line, re.I), line
        assert not re.search(r"^\s*(export |sudo |\$ )", text, re.M)
        assert "```bash" not in text and "```sh" not in text
        assert not re.search(r"\buv run pytest\b|\buv run uvicorn\b", text)
        assert not re.search(r"\bdbc-[0-9a-f]{8}\b", text)
    for cmd in (
        "demo seed",
        "demo seed-systems",
        "preflight",
        "tools\\smoke_launch.py",
        "pip install -r requirements.txt",
    ):
        assert cmd in laptop, cmd
    for cmd in ("bundle validate", "bundle deploy", "bundle run supervisor", "bootstrap_schema"):
        assert cmd in dbx, cmd
    for n in range(13, 17):
        assert f"| {n} |" in (REPO_ROOT / "docs/live-test-kit.md").read_text(encoding="utf-8")


def test_docs_reference_files_that_exist() -> None:
    for rel in ("tools/smoke_launch.py", ".env.laptop.example", "docs/RUNBOOK.md"):
        assert (REPO_ROOT / rel).is_file(), rel
    for doc in ("docs/deploy/LAUNCH_LAPTOP.md", "docs/deploy/LAUNCH_DATABRICKS.md"):
        text = (REPO_ROOT / doc).read_text(encoding="utf-8")
        for ref in re.findall(r"`(docs\\[A-Za-z0-9_.\\-]+\.md)`", text):
            assert (REPO_ROOT / ref.replace("\\", "/")).is_file(), f"{doc}: {ref}"

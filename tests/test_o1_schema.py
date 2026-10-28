"""WP-O1: the table intake_attempt (schema/model.yaml, DDL, notebook) and the three settings."""

from __future__ import annotations

from supervisor.config import load_settings
from supervisor.core.schema import DDL_DIR, load_model
from tests.conftest import REPO_ROOT

COLUMNS = [
    "attempt_id",
    "node_id",
    "n",
    "source_kind",
    "source_ref",
    "sha256",
    "size_bytes",
    "file_count",
    "created_by",
    "created_at",
    "status",
    "detail",
]


def test_intake_attempt_is_a_state_table_with_the_planned_columns() -> None:
    t = load_model().table("intake_attempt")
    assert t.kind == "state" and not t.append_only
    assert t.primary_key == ("attempt_id",) or list(t.primary_key) == ["attempt_id"]
    names = [c.name for c in t.columns]
    assert names[: len(COLUMNS)] == COLUMNS
    assert {"row_version", "updated_at"} <= set(names)  # added to every state table
    by_name = {c.name: c for c in t.columns}
    assert by_name["detail"].nullable and not by_name["n"].nullable


def test_intake_attempt_is_in_both_ddl_files_and_the_notebook() -> None:
    sqlite = (DDL_DIR / "sqlite.sql").read_text(encoding="utf-8")
    dbx = (DDL_DIR / "databricks.sql").read_text(encoding="utf-8")
    nb = (REPO_ROOT / "notebooks" / "bootstrap_and_smoke.py").read_text(encoding="utf-8")
    assert "CREATE TABLE IF NOT EXISTS intake_attempt" in sqlite
    assert "`${schema}`.`intake_attempt`" in dbx and "`${schema}`.`intake_attempt`" in nb


def test_the_table_is_the_last_one_of_model_yaml_until_a_later_wp_adds_more() -> None:
    """Merge hint: other WPs append to the end of the model too; this only checks the order of
    the WP-O1 table relative to the Phase 10 tables (it comes after guardian_off_request)."""
    names = list(load_model().tables)
    assert names.index("intake_attempt") > names.index("guardian_off_request")


def test_settings_defaults_and_env(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    s = load_settings(sql_backend="sqlite")
    assert (s.onboard_intake, s.onboard_intake_max_mb, s.onboard_git_hosts) == (False, 20, "")
    monkeypatch.setenv("ONBOARD_INTAKE", "1")
    monkeypatch.setenv("ONBOARD_INTAKE_MAX_MB", "5")
    monkeypatch.setenv("ONBOARD_GIT_HOSTS", "a.example.invalid, B.example.invalid")
    s = load_settings(sql_backend="sqlite")
    assert (s.onboard_intake, s.onboard_intake_max_mb) == (True, 5)
    from supervisor.onboard.intake import git_hosts

    assert git_hosts(s) == ("a.example.invalid", "b.example.invalid")

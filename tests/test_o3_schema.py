"""WP-O3: the table predeploy_report (schema/model.yaml, DDL, notebook) and the setting."""

from __future__ import annotations

from supervisor.config import load_settings
from supervisor.core.schema import DDL_DIR, load_model
from tests.conftest import REPO_ROOT

COLUMNS = [
    "report_id",
    "node_id",
    "attempt_n",
    "status",
    "verdict",
    "started_at",
    "finished_at",
    "items_total",
    "items_fail",
    "items_question",
    "summary",
    "items",
    "model_id",
    "created_by",
    "created_at",
]


def test_predeploy_report_is_a_state_table_with_the_planned_columns() -> None:
    t = load_model().table("predeploy_report")
    assert t.kind == "state" and not t.append_only
    assert list(t.primary_key) == ["report_id"]
    names = [c.name for c in t.columns]
    assert names[: len(COLUMNS)] == COLUMNS
    assert {"row_version", "updated_at"} <= set(names)  # added to every state table
    by_name = {c.name: c for c in t.columns}
    for required in ("attempt_n", "status", "verdict", "items_total", "items", "summary"):
        assert not by_name[required].nullable, required
    for nullable in ("finished_at", "model_id"):
        assert by_name[nullable].nullable, nullable
    assert by_name["attempt_n"].type == "int" and by_name["items_fail"].type == "int"


def test_predeploy_report_is_in_both_ddl_files_and_the_notebook() -> None:
    sqlite = (DDL_DIR / "sqlite.sql").read_text(encoding="utf-8")
    dbx = (DDL_DIR / "databricks.sql").read_text(encoding="utf-8")
    nb = (REPO_ROOT / "notebooks" / "bootstrap_and_smoke.py").read_text(encoding="utf-8")
    assert "CREATE TABLE IF NOT EXISTS predeploy_report" in sqlite
    assert "`${schema}`.`predeploy_report`" in dbx and "`${schema}`.`predeploy_report`" in nb


def test_the_table_comes_after_onboard_facts_in_the_model() -> None:
    """Merge hint: other WPs append to the end of the model too; only the order against WP-O2."""
    names = list(load_model().tables)
    assert names.index("predeploy_report") > names.index("onboard_facts")


def test_setting_defaults_off_and_reads_the_environment(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    assert load_settings(sql_backend="sqlite").onboard_predeploy is False
    monkeypatch.setenv("ONBOARD_PREDEPLOY", "1")
    assert load_settings(sql_backend="sqlite").onboard_predeploy is True


def test_app_yaml_has_the_commented_line_and_no_active_one() -> None:
    text = (REPO_ROOT / "app.yaml").read_text(encoding="utf-8")
    assert "# - name: ONBOARD_PREDEPLOY" in text
    assert "\n  - name: ONBOARD_PREDEPLOY" not in text

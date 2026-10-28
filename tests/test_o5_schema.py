"""WP-O5: the table onboard_log (schema/model.yaml, DDL, notebook) and the setting."""

from __future__ import annotations

from supervisor.config import load_settings
from supervisor.core.schema import DDL_DIR, load_model
from supervisor.onboard import agent_log
from tests.conftest import REPO_ROOT

COLUMNS = [
    "log_id",
    "node_id",
    "attempt_n",
    "step",
    "what",
    "pointer",
    "by_kind",
    "actor",
    "at",
]


def test_onboard_log_is_an_append_only_table_with_the_planned_columns() -> None:
    t = load_model().table("onboard_log")
    assert t.kind == "append_only" and t.append_only
    assert list(t.primary_key) == ["log_id"]
    assert [c.name for c in t.columns] == COLUMNS
    by_name = {c.name: c for c in t.columns}
    assert by_name["attempt_n"].nullable and by_name["attempt_n"].type == "int"
    for required in ("log_id", "node_id", "step", "what", "pointer", "by_kind", "actor", "at"):
        assert not by_name[required].nullable, required
    assert by_name["at"].type == "timestamp" and by_name["what"].type == "text"
    assert not any(c.type.rstrip("?") == "float" for c in t.columns)  # no floats


def test_onboard_log_is_in_both_ddl_files_and_the_notebook() -> None:
    sqlite = (DDL_DIR / "sqlite.sql").read_text(encoding="utf-8")
    dbx = (DDL_DIR / "databricks.sql").read_text(encoding="utf-8")
    nb = (REPO_ROOT / "notebooks" / "bootstrap_and_smoke.py").read_text(encoding="utf-8")
    assert "CREATE TABLE IF NOT EXISTS onboard_log" in sqlite
    assert "`${schema}`.`onboard_log`" in dbx and "`${schema}`.`onboard_log`" in nb
    assert "BEFORE UPDATE ON onboard_log" in sqlite and "BEFORE DELETE ON onboard_log" in sqlite
    block = dbx.split("`${schema}`.`onboard_log`", 1)[1].split("CREATE TABLE", 1)[0]
    assert "delta.appendOnly" in block


def test_the_table_comes_after_predeploy_report_in_the_model() -> None:
    """Merge hint: other WPs append to the end of the model too; only the order against WP-O3."""
    names = list(load_model().tables)
    assert names.index("onboard_log") > names.index("predeploy_report")


def test_steps_and_kinds_in_the_writer_match_the_schema_comment() -> None:
    text = (REPO_ROOT / "schema" / "model.yaml").read_text(encoding="utf-8")
    text = text.split("\n  onboard_log:", 1)[1]
    comment = next(line for line in text.splitlines() if line.strip().startswith("step: string"))
    for step in agent_log.STEPS:
        assert step in comment, step
    assert agent_log.BY_KINDS == ("model", "rule", "person")


def test_setting_defaults_off_and_reads_the_environment(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    assert load_settings(sql_backend="sqlite").onboard_postdeploy is False
    monkeypatch.setenv("ONBOARD_POSTDEPLOY", "1")
    assert load_settings(sql_backend="sqlite").onboard_postdeploy is True


def test_app_yaml_has_the_commented_line_and_no_active_one() -> None:
    text = (REPO_ROOT / "app.yaml").read_text(encoding="utf-8")
    assert "# - name: ONBOARD_POSTDEPLOY" in text
    assert "\n  - name: ONBOARD_POSTDEPLOY" not in text

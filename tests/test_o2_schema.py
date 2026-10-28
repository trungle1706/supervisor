"""WP-O2: the table onboard_facts (schema/model.yaml, DDL, notebook), the setting and the new
inventory edge source."""

from __future__ import annotations

from supervisor.config import load_settings
from supervisor.core.schema import DDL_DIR, load_model
from supervisor.inventory.model import SOURCES, Edge
from tests.conftest import REPO_ROOT

COLUMNS = [
    "fact_id",
    "node_id",
    "attempt_n",
    "kind",
    "name",
    "detail",
    "file",
    "line",
    "quote",
    "source",
    "model_id",
    "dropped_claims",
    "active",
    "created_at",
]


def test_onboard_facts_is_a_state_table_with_the_planned_columns() -> None:
    t = load_model().table("onboard_facts")
    assert t.kind == "state" and not t.append_only
    assert list(t.primary_key) == ["fact_id"]
    names = [c.name for c in t.columns]
    assert names[: len(COLUMNS)] == COLUMNS
    assert {"row_version", "updated_at"} <= set(names)  # added to every state table
    by_name = {c.name: c for c in t.columns}
    assert not by_name["attempt_n"].nullable and not by_name["kind"].nullable
    for nullable in ("detail", "file", "line", "quote", "model_id", "dropped_claims"):
        assert by_name[nullable].nullable, nullable


def test_onboard_facts_is_in_both_ddl_files_and_the_notebook() -> None:
    sqlite = (DDL_DIR / "sqlite.sql").read_text(encoding="utf-8")
    dbx = (DDL_DIR / "databricks.sql").read_text(encoding="utf-8")
    nb = (REPO_ROOT / "notebooks" / "bootstrap_and_smoke.py").read_text(encoding="utf-8")
    assert "CREATE TABLE IF NOT EXISTS onboard_facts" in sqlite
    assert "`${schema}`.`onboard_facts`" in dbx and "`${schema}`.`onboard_facts`" in nb


def test_the_table_comes_after_intake_attempt_in_the_model() -> None:
    """Merge hint: other WPs append to the end of the model too; only the order against WP-O1."""
    names = list(load_model().tables)
    assert names.index("onboard_facts") > names.index("intake_attempt")


def test_setting_defaults_and_env(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    assert load_settings(sql_backend="sqlite").onboard_facts is False
    monkeypatch.setenv("ONBOARD_FACTS", "1")
    assert load_settings(sql_backend="sqlite").onboard_facts is True


def test_onboard_facts_is_an_inventory_edge_source() -> None:
    assert "onboard_facts" in SOURCES
    e = Edge("a", "b", "uses", "onboard_facts", "agent.py:3")
    assert e.source == "onboard_facts"

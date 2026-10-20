"""WP31 on the Delta path (databricks_fake): the table is in both DDLs and a report row is an
insert-only MERGE with typed values."""

from __future__ import annotations

from datetime import UTC, datetime

from supervisor.adapters.clock import FixedClock
from supervisor.adapters.sql.databricks_fake import FakeStatementExecution, dml_result
from supervisor.adapters.sql.databricks_rest import DatabricksRestExecutor
from supervisor.adapters.sql.store import SqlTableStore
from supervisor.core.schema import load_model
from tests.conftest import REPO_ROOT

T0 = datetime(2026, 10, 20, 5, 0, 0, tzinfo=UTC)


def test_report_row_is_an_insert_only_merge() -> None:
    fake = FakeStatementExecution()
    fake.add(dml_result(1), match="MERGE INTO `c`.`s`.`transparency_report`")
    ex = DatabricksRestExecutor(fake, warehouse_id="wh", catalog="c", schema="s")
    tables = SqlTableStore(ex, load_model())
    cols = load_model().table("transparency_report").column_names
    row = {c: 0 for c in cols} | {
        "report_id": "tr_1", "agent_id": "payments", "variant": "customer", "lang": "vi",
        "generated_at": T0, "generated_by": "u", "content_hash": "0" * 64,
        "json_hash": "1" * 64, "html_hash": "2" * 64, "pdf_hash": None,
        "section_hashes": {"identity": "3" * 64}, "verify_state": "ok", "chain_hash": None,
    }  # fmt: skip
    assert tables.append("transparency_report", [row]) == 1
    (stmt,) = [s for s in fake.statements if "transparency_report" in s]
    assert "WHEN NOT MATCHED THEN INSERT" in stmt and "WHEN MATCHED" not in stmt
    assert fake.remaining() == 0
    assert FixedClock(T0).now() == T0


def test_table_is_in_both_ddls_and_the_model_is_append_only() -> None:
    sq = (REPO_ROOT / "schema" / "ddl" / "sqlite.sql").read_text(encoding="utf-8")
    dl = (REPO_ROOT / "schema" / "ddl" / "databricks.sql").read_text(encoding="utf-8")
    assert "transparency_report" in sq and "transparency_report" in dl
    assert load_model().table("transparency_report").kind == "append_only"

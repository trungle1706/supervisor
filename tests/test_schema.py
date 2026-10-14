from __future__ import annotations

import pytest

from schema.generate import main as generate_main
from schema.generate import outputs
from supervisor.core.schema import DDL_DIR, MODEL_PATH, load_model, parse_model


def test_ddl_regenerates_byte_identical() -> None:
    for name, text in outputs().items():
        assert (DDL_DIR / name).read_bytes() == text.encode("utf-8"), (
            f"{name} is stale: run uv run python -m schema.generate"
        )
    assert generate_main(["--check"]) == 0


def test_append_only_tables_have_triggers_and_delta_property() -> None:
    model = load_model()
    sqlite = (DDL_DIR / "sqlite.sql").read_text(encoding="utf-8")
    dbx = (DDL_DIR / "databricks.sql").read_text(encoding="utf-8")
    for t in model.tables.values():
        has_trg = (
            f"BEFORE UPDATE ON {t.name}\n" in sqlite and f"BEFORE DELETE ON {t.name}\n" in sqlite
        )
        assert has_trg == t.append_only, t.name
        assert f"`${{catalog}}`.`${{schema}}`.`{t.name}`" in dbx
    for name in ("agent_event", "verdict", "case_event", "signoff", "chain_entry", "anchor"):
        assert model.table(name).append_only
    assert dbx.count("'delta.appendOnly' = 'true'") == sum(
        t.append_only for t in model.tables.values()
    )


def test_state_tables_get_row_version() -> None:
    for t in load_model().tables.values():
        assert ("row_version" in t.column_names) == (t.kind == "state")


@pytest.mark.parametrize(
    "snippet,error",
    [
        ("x: {kind: state, primary_key: [a], columns: {a: nope}}", "unknown type"),
        ("x: {kind: state, primary_key: [a], columns: {a: float, fee_minor: int}}", "money"),
        ("x: {kind: state, primary_key: [a], columns: {a: money}}", "_minor"),
        ("x: {kind: state, primary_key: [a], columns: {a: 'string?'}}", "nullable"),
        ("x: {kind: state, primary_key: [b], columns: {a: string}}", "not defined"),
        ("x: {kind: weird, primary_key: [a], columns: {a: string}}", "kind"),
    ],
)
def test_model_validation(snippet: str, error: str) -> None:
    with pytest.raises(ValueError, match=error):
        parse_model("version: 1\ntables:\n  " + snippet + "\n")


def test_model_path_is_absolute() -> None:
    assert MODEL_PATH.is_absolute() and MODEL_PATH.exists()

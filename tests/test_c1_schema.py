"""WP-C1: the table classification_v2 (schema/model.yaml, DDL, notebook), the setting, app.yaml,
the i18n keys and the CSP-safe templates."""

from __future__ import annotations

import re

from supervisor.config import load_settings
from supervisor.console.i18n import _T
from supervisor.core.schema import DDL_DIR, load_model
from tests.conftest import REPO_ROOT

COLUMNS = [
    "classification_id",
    "system_id",
    "outcome",
    "path_json",
    "tree_sha256",
    "path_hash",
    "decided_by",
    "approved_by",
    "approved_at",
    "inherited_from_provider",
    "valid_until",
    "created_at",
]


def test_table_has_the_planned_columns_and_no_floats() -> None:
    t = load_model().table("classification_v2")
    assert t.kind == "state"
    assert list(t.primary_key) == ["classification_id"]
    assert [c.name for c in t.columns][: len(COLUMNS)] == COLUMNS  # then the state columns
    assert "row_version" in [c.name for c in t.columns]
    by = {c.name: c for c in t.columns}
    assert by["approved_by"].nullable and by["approved_at"].nullable
    assert not by["decided_by"].nullable and not by["valid_until"].nullable
    assert by["path_json"].type == "json" and by["inherited_from_provider"].type == "bool"
    assert not any(c.type.rstrip("?") == "float" for c in t.columns)


def test_table_is_the_last_one_and_in_both_ddl_files_and_the_notebook() -> None:
    names = list(load_model().tables)
    assert names.index("classification_v2") > names.index("onboard_log")
    sqlite = (DDL_DIR / "sqlite.sql").read_text(encoding="utf-8")
    dbx = (DDL_DIR / "databricks.sql").read_text(encoding="utf-8")
    nb = (REPO_ROOT / "notebooks" / "bootstrap_and_smoke.py").read_text(encoding="utf-8")
    assert "CREATE TABLE IF NOT EXISTS classification_v2" in sqlite
    assert "`${schema}`.`classification_v2`" in dbx and "`${schema}`.`classification_v2`" in nb


def test_setting_defaults_off_and_reads_the_environment(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    s = load_settings(sql_backend="sqlite")
    assert s.classification_v2 is False
    assert s.classification_config.is_absolute() and s.classification_config.is_file()
    monkeypatch.setenv("CLASSIFICATION_V2", "1")
    assert load_settings(sql_backend="sqlite").classification_v2 is True


def test_app_yaml_has_the_commented_line_and_no_active_one() -> None:
    text = (REPO_ROOT / "app.yaml").read_text(encoding="utf-8")
    assert "# - name: CLASSIFICATION_V2" in text
    assert "\n  - name: CLASSIFICATION_V2" not in text


def test_i18n_keys_exist_in_both_languages_and_the_templates_use_known_keys() -> None:
    keys = {k for k in _T if k.startswith("cv_")}
    assert len(keys) > 50
    for k in keys:
        en, vi = _T[k]
        assert en.strip() and vi.strip(), k
    used: set[str] = set()
    for name in ("_classify_tree.html", "_classify_panel.html", "classify.html"):
        text = (REPO_ROOT / "src/supervisor/console/templates" / name).read_text(encoding="utf-8")
        used |= set(re.findall(r"t\('(cv_[a-z0-9_]+)'\)", text))
    assert used and used <= keys, sorted(used - keys)
    # the keys built from a variable: answers, sources, states, reasons, thresholds
    for k in (
        "cv_yes",
        "cv_no",
        "cv_excluded",
        "cv_src_rules",
        "cv_src_person",
        "cv_src_decision33",
        "cv_status_on",
        "cv_status_open",
        "cv_status_off",
        "cv_reason_unanswered",
        "cv_reason_decision33_open",
        "cv_th_credit_vnd",
        "cv_th_personal_per_day_vnd",
    ):
        assert k in keys, k


def test_templates_hold_no_script_and_no_inline_handler() -> None:
    for name in ("_classify_tree.html", "_classify_panel.html", "classify.html"):
        text = (REPO_ROOT / "src/supervisor/console/templates" / name).read_text(encoding="utf-8")
        low = text.lower()
        assert "<script" not in low and "javascript:" not in low, name
        assert not re.search(r"\son[a-z]+=", low), name

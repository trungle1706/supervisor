"""WP-P3: the schema self-check page (admin only) and the banner on admin pages."""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any

import pytest
from fastapi.testclient import TestClient

from supervisor.core.errors import SqlError
from supervisor.ops import schema_selfcheck
from supervisor.ops.schema_selfcheck import SchemaCheck


@pytest.fixture(autouse=True)
def _clean_state() -> Iterator[None]:
    schema_selfcheck.set_state(None)
    yield
    schema_selfcheck.set_state(None)


@pytest.fixture
def admin_console(console: Any) -> Any:
    return console


def test_schema_page_admin_only_and_shows_plan(admin_console: Any) -> None:
    plan = "CREATE TABLE IF NOT EXISTS `main`.`sup`.`cases` (a STRING)"
    schema_selfcheck.set_state(
        SchemaCheck(
            "missing",
            "2026-10-28T00:00:00Z",
            60,
            ("cases",),
            (("agent", ("plug_point",)),),
            (plan,),
        )
    )
    denied = admin_console.get("/console/admin/schema", user="viewer.hoa")
    assert denied.status_code in (400, 403) and plan not in denied.text
    ok = admin_console.get("/console/admin/schema", user="admin.chi")
    assert ok.status_code == 200
    assert "CREATE TABLE IF NOT EXISTS `main`.`sup`.`cases`" in ok.text
    assert "plug_point" in ok.text


def test_banner_on_admin_pages_only_while_schema_differs(admin_console: Any) -> None:
    schema_selfcheck.set_state(SchemaCheck("missing", "t", 60, ("cases",), (), ("x",)))
    assert "data-schema-banner" in admin_console.get("/console/", user="admin.chi").text
    assert "data-schema-banner" not in admin_console.get("/console/", user="reviewer.an").text
    schema_selfcheck.set_state(SchemaCheck("ok", "t", 60))
    assert "data-schema-banner" not in admin_console.get("/console/", user="admin.chi").text


def test_off_path_page_and_pages_unchanged(admin_console: Any) -> None:
    page = admin_console.get("/console/admin/schema", user="admin.chi")
    assert page.status_code == 200 and "SCHEMA_SELFCHECK" in page.text
    assert "data-schema-banner" not in admin_console.get("/console/", user="admin.chi").text


def test_page_answers_without_console_context(monkeypatch: pytest.MonkeyPatch) -> None:
    """A missing table can stop the runtime; the plan page must still open."""
    from supervisor.app import app
    from supervisor.console import context as console_context
    from supervisor.console import routes

    def broken() -> Any:
        raise SqlError("TABLE_OR_VIEW_NOT_FOUND agent")

    monkeypatch.setattr(routes, "get_context", broken)
    monkeypatch.setattr(console_context, "get_context", broken)
    schema_selfcheck.set_state(
        SchemaCheck(
            "missing", "t", 60, ("cases",), (), ("CREATE TABLE IF NOT EXISTS x (a STRING)",)
        )
    )
    r = TestClient(app).get("/console/admin/schema", headers={"X-Dev-User": "admin.chi"})
    assert r.status_code == 200
    assert "CREATE TABLE IF NOT EXISTS x" in r.text and "SqlError" in r.text

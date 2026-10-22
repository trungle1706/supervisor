"""Regression: the governance fixtures mount routers on the global app. ``include_router`` wraps
``app.router.lifespan_context`` each time, so a fixture that restores only the routes makes the
app start-up recurse (RecursionError in tests/test_wiring.py and tests/monitors/test_lifespan.py
after several hundred tests). The file name sorts last so it sees what the others left."""

from __future__ import annotations

from supervisor.app import app

from .conftest import APP_LIFESPAN, Console, restore_app


def test_the_app_lifespan_is_the_one_before_the_tests() -> None:
    assert app.router.lifespan_context is APP_LIFESPAN


def test_a_mounted_fixture_leaves_the_lifespan_as_it_was(on: Console) -> None:
    # while mounted the chain is deeper; the teardown (restore_app) must undo it
    assert app.router.lifespan_context is not APP_LIFESPAN


def test_restore_app_puts_back_routes_and_lifespan() -> None:
    routes = list(app.router.routes)
    marker = object()
    before = app.router.lifespan_context
    app.router.lifespan_context = marker  # type: ignore[assignment]
    restore_app(app, routes, before)
    assert app.router.lifespan_context is before

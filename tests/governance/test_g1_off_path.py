"""WP-G1 off path: with the flags off nothing is mounted and nothing changes; task sizing of an
agent that is not linked to a system is byte-identical to the one before WP-G1."""

from __future__ import annotations

import hashlib
import json

import pytest

from supervisor.app import app
from supervisor.config import Settings, load_settings
from supervisor.tasks.model import CLASSES, LEVELS, STAGES, effective_level, load_config, plan
from supervisor.tasks.model import stages_in_use

from .conftest import Console

# sha256 of the plan of every (Decision 33 class, band) pair, computed from config/tasks.yaml
# before WP-G1 (see test_plan_hash_is_the_one_before_wp_g1).
PLAN_HASH_BEFORE_G1 = "b02991ffb24b116e2e0c57d82cb1c4c0bb1689926ead2508f1661d473db43b05"

G1_PATHS = ("/approvals", "/reviews", "/stage")


def _paths() -> set[str]:
    from tests.console.test_rbac_matrix import app_routes

    return {p for _, p, _ in app_routes()}


def test_g1_flags_are_off_by_default() -> None:
    assert Settings.model_fields["webhooks_enabled"].default is False
    s = load_settings(sql_backend="sqlite", llm_base_url="")
    assert s.webhooks_enabled is False and s.governance_enabled is False


def test_no_g1_route_is_mounted_with_the_flags_off() -> None:
    bad = [p for p in _paths() if p.startswith("/v1/systems") and p.endswith(G1_PATHS)]
    bad += [p for p in _paths() if "/approvals" in p or "/reviews" in p]
    assert not bad
    assert not [p for p in app.openapi()["paths"] if p.startswith("/v1/systems")]


@pytest.mark.parametrize(
    "path",
    [
        "/v1/systems/sys_x/approvals",
        "/v1/systems/sys_x/reviews",
        "/v1/systems/sys_x/stage",
        "/v1/systems/sys_x/reviews/r1/complete",
    ],
)
def test_g1_urls_do_not_exist_with_the_flags_off(console: Console, path: str) -> None:
    for method in ("GET", "POST"):
        r = console.client.request(method, path, json={}, headers={"X-Dev-User": "reviewer.an"})
        assert r.status_code in (404, 405)


def test_g1_tables_stay_empty_with_the_flags_off(console: Console) -> None:
    for table in ("stage_approval", "review", "outbound_event"):
        assert console.ctx.state.query(table) == []


def test_plan_hash_is_the_one_before_wp_g1() -> None:
    cfg = load_config()
    out = {}
    for c in CLASSES:
        for b in LEVELS:
            p = plan(cfg, c, b)
            out[f"{c}/{b}"] = {
                "lvl": effective_level(cfg, c, b),
                "stages": stages_in_use(cfg, c, b),
                "t": {s: [(x.template.id, x.required) for x in p[s]] for s in STAGES},
            }
    digest = hashlib.sha256(json.dumps(out, sort_keys=True).encode()).hexdigest()
    assert digest == PLAN_HASH_BEFORE_G1

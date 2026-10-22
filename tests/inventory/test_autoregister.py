"""WP-G3: draft AI systems from the workspace scan (INVENTORY_AUTOREGISTER + GOVERNANCE_ENABLED).

The off path comes first: with the flag off the scan result and the tables are as before."""

from __future__ import annotations

import json
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest

from supervisor.adapters.factory import Adapters, build_adapters
from supervisor.adapters.workspace.fixtures import FixtureWorkspaceReader
from supervisor.config import load_settings
from supervisor.governance.systems import SystemService
from supervisor.inventory.autoregister import GovernanceConfig, resolve_owner
from supervisor.inventory.service import InventoryService
from supervisor.jobs import bootstrap_schema
from supervisor.tasks.service import TaskService
from tests.conftest import REPO_ROOT
from tests.inventory.conftest import WORKSPACE_7, ListSink

V2 = REPO_ROOT / "tests" / "fixtures" / "inventory" / "workspace_v2.json"
CONFIG = """\
default_owner:
  owner_user: owner.default@example.invalid
  owner_team: Default Team
default_owner_by_catalog:
  MAIN:
    owner_user: owner.main@example.invalid
    owner_team: Lending Data
default_owner_by_group:
  risk-analysts:
    owner_user: owner.risk@example.invalid
    owner_team: Risk Analytics
"""


def _adapters(tmp_path: Path, **flags: Any) -> Iterator[Adapters]:
    cfg = tmp_path / "governance.yaml"
    if not cfg.exists():
        cfg.write_text(CONFIG, encoding="utf-8")
    allow = tmp_path / "allow.yaml"
    allow.write_text("genie_spaces:\n  - known bi*\n", encoding="utf-8")
    settings = load_settings(
        inventory_allowlist_file=allow,
        sql_backend="sqlite",
        data_dir=tmp_path / "data",
        llm_base_url="",
        inventory_enabled=True,
        inventory_scan_v2=True,
        governance_config_file=cfg,
        **flags,
    )
    a = build_adapters(settings)
    bootstrap_schema.run(a.settings, a)
    try:
        yield a
    finally:
        a.close()


@pytest.fixture
def on(tmp_path: Path) -> Iterator[Adapters]:
    yield from _adapters(tmp_path, governance_enabled=True, inventory_autoregister=True)


@pytest.fixture
def sink() -> ListSink:
    return ListSink()


def _services(a: Adapters, sink: ListSink) -> tuple[SystemService, TaskService]:
    return SystemService.from_adapters(a, sink), TaskService.from_adapters(a, sink)


def _refresh(a: Adapters, sink: ListSink, path: Path = V2) -> dict[str, Any]:
    systems, tasks = _services(a, sink)
    return InventoryService.from_adapters(a).refresh_workspace(
        FixtureWorkspaceReader.from_file(path), None, systems, tasks
    )


# ------------------------------------------------------------------------------- off path


def test_flag_off_changes_nothing_even_with_governance_on(tmp_path: Path, sink: ListSink) -> None:
    for a in _adapters(tmp_path, governance_enabled=True):  # INVENTORY_AUTOREGISTER unset
        out = _refresh(a, sink)
        assert set(out) == {"apply", "shadow", "errors"}  # no "autoregister" entry
        assert a.state.query("ai_system") == []
        assert a.state.query("system_component") == []
        assert a.state.query("task") == []
        assert not [r for r in sink.records if r[0] in ("system_change", "task_change")]


def test_default_is_off() -> None:
    assert load_settings(sql_backend="sqlite").inventory_autoregister is False


def test_seven_item_fixture_is_unchanged_with_the_flag_off(tmp_path: Path, sink: ListSink) -> None:
    for a in _adapters(tmp_path):
        InventoryService.from_adapters(a).fill_manifests()
        out = _refresh(a, sink, WORKSPACE_7)
        assert out["errors"] == {} and set(out) == {"apply", "shadow", "errors"}
        # 3 managed, 4 unmanaged (no app on the allow-list here, so bi-portal counts too)
        assert (out["shadow"]["managed"], out["shadow"]["unmanaged"]) == (3, 4)


def test_flag_on_but_governance_off_is_a_skip_not_a_failure(tmp_path: Path, sink: ListSink) -> None:
    for a in _adapters(tmp_path, inventory_autoregister=True):
        out = _refresh(a, sink)
        assert out["autoregister"]["status"] == "skipped"
        assert "GOVERNANCE_ENABLED" in out["autoregister"]["reason"]
        assert a.state.query("ai_system") == []


# ------------------------------------------------------------------------------- on


def test_unmanaged_app_agent_endpoint_and_genie_space_get_a_draft(
    on: Adapters, sink: ListSink
) -> None:
    out = _refresh(on, sink)
    assert out["autoregister"] == {
        "status": "ran",
        "created": 3,
        "already_registered": 0,
        "skipped_no_owner": 0,
        "skipped_name": 0,
        "errors": 0,
    }
    rows = {r["name"]: r for r in on.state.query("ai_system")}
    assert set(rows) == {"loan-copilot", "agent-credit-memo", "Lending analytics"}
    for r in rows.values():
        assert r["status"] == "draft" and r["risk_level"] == "unspecified"
        assert r["lifecycle_stage"] == "initiation" and r["decision33_class"] == "unclassified"
        tags = r["tags"] if isinstance(r["tags"], dict) else json.loads(r["tags"])
        assert tags["source"] == "workspace_scan" and tags["node_id"].startswith("inv_")
        assert tags["intake_defaults"] == "true"
    # Owners: catalog MAIN (case-insensitive) for the Genie space and the agent endpoint (its
    # served model lives in catalog main); the App reads no table, so the default owner.
    assert rows["Lending analytics"]["owner_user"] == "owner.main@example.invalid"
    assert rows["agent-credit-memo"]["owner_team"] == "Lending Data"
    assert rows["loan-copilot"]["owner_user"] == "owner.default@example.invalid"
    # not registered: a plain LLM gateway endpoint, a vector index, a job, a function
    assert "gpt-gateway" not in rows and "nightly-memo-batch" not in rows


def test_node_is_linked_and_initiation_task_is_open(on: Adapters, sink: ListSink) -> None:
    _refresh(on, sink)
    svc = SystemService.from_adapters(on)
    sysrow = next(r for r in on.state.query("ai_system") if r["name"] == "Lending analytics")
    view = svc.get(sysrow["system_id"])
    comps = view["components"]
    assert len(comps) == 1
    assert comps[0]["ref_kind"] == "node" and comps[0]["source"] == "workspace_scan"
    assert comps[0]["evidence_ref"] == "workspace:genie-space/Lending analytics"
    tasks = on.state.query("task", {"agent_id": sysrow["system_id"]})
    assert len(tasks) == 1
    t = tasks[0]
    assert (
        t["title"].startswith("Confirm context")
        and "to confirm" in t["title"]
        and t["stage"] == "initiation"
        and t["status"] == "open"
    )
    assert t["required"] in (True, 1)


def test_second_scan_creates_nothing_and_an_archived_draft_does_not_come_back(
    on: Adapters, sink: ListSink
) -> None:
    _refresh(on, sink)
    n_sys = len(on.state.query("ai_system"))
    again = _refresh(on, sink)["autoregister"]
    assert again["created"] == 0 and again["already_registered"] == 3
    assert len(on.state.query("ai_system")) == n_sys
    svc = SystemService.from_adapters(on, sink)
    sid = on.state.query("ai_system")[0]["system_id"]
    svc.archive(sid, "admin")
    assert _refresh(on, sink)["autoregister"]["created"] == 0
    assert len(on.state.query("ai_system")) == n_sys
    assert len(on.state.query("task")) == 3  # one initiation task per draft, never a second


def test_chain_records_carry_no_workspace_name(on: Adapters, sink: ListSink) -> None:
    _refresh(on, sink)
    recs = [r for r in sink.records if r[0] in ("system_change", "task_change")]
    assert {r[0] for r in recs} == {"system_change", "task_change"}
    dump = json.dumps(recs)
    for name in ("loan-copilot", "Lending analytics", "agent-credit-memo", "workspace:"):
        assert name not in dump


def test_name_taken_by_a_person_gets_a_qualified_name(on: Adapters, sink: ListSink) -> None:
    systems, _ = _services(on, sink)
    systems.register(
        {
            "name": "loan-copilot",
            "owner_user": "someone@example.invalid",
            "owner_team": "Lending",
            "purpose": "made by a person",
            "system_type": "assistant",
            "org_role": "deployer",
            "user_segment": "internal",
            "personal_data": "none",
            "human_control": "post_review",
        },
        "someone@example.invalid",
    )
    out = _refresh(on, sink)["autoregister"]
    assert out["created"] == 3
    assert "loan-copilot (app)" in {r["name"] for r in on.state.query("ai_system")}


def test_fill_me_owner_means_no_draft(tmp_path: Path, sink: ListSink) -> None:
    cfg = tmp_path / "governance.yaml"
    cfg.write_text(
        "default_owner:\n  owner_user: FILL-ME-owner-user\n  owner_team: FILL-ME-owner-team\n",
        encoding="utf-8",
    )
    for a in _adapters(tmp_path, governance_enabled=True, inventory_autoregister=True):
        out = _refresh(a, sink)["autoregister"]
        assert out["created"] == 0 and out["skipped_no_owner"] == 3
        assert a.state.query("ai_system") == []


def test_committed_config_has_only_placeholders() -> None:
    cfg = GovernanceConfig.load(REPO_ROOT / "config" / "governance.yaml")
    assert cfg.default_owner is not None and not cfg.default_owner.usable()
    assert cfg.by_group == {} and cfg.by_catalog == {}
    assert cfg.task_title == "Confirm context"


def test_group_beats_catalog_beats_default(on: Adapters, sink: ListSink) -> None:
    _refresh(on, sink)
    g = InventoryService.from_adapters(on).store.load_graph()
    cfg = GovernanceConfig.load(on.settings.governance_config_file)
    genie = next(n for n in g.nodes.values() if n.display_name == "Lending analytics")
    assert resolve_owner(g, genie, cfg).owner_team == "Lending Data"  # type: ignore[union-attr]
    genie.attrs["owner_group"] = "Risk-Analysts"
    assert resolve_owner(g, genie, cfg).owner_team == "Risk Analytics"  # type: ignore[union-attr]
    app = next(n for n in g.nodes.values() if n.display_name == "loan-copilot")
    assert resolve_owner(g, app, cfg).owner_team == "Default Team"  # type: ignore[union-attr]


def test_a_failing_system_service_never_fails_the_scan(on: Adapters, sink: ListSink) -> None:
    class Broken:
        def register(self, *a: Any, **k: Any) -> Any:
            raise RuntimeError("boom")

    out = InventoryService.from_adapters(on).refresh_workspace(
        FixtureWorkspaceReader.from_file(V2), None, Broken(), None
    )
    assert out["errors"] == {} and out["apply"]["nodes_new"] > 0
    assert out["autoregister"]["errors"] == 3 and out["autoregister"]["created"] == 0


def test_scan_does_not_pause_or_block_anything(on: Adapters, sink: ListSink) -> None:
    """The scan only writes inventory, ai_system, system_component and task rows."""
    before = {t: len(on.state.query(t)) for t in ("agent", "gate_control")}
    _refresh(on, sink)
    assert {t: len(on.state.query(t)) for t in before} == before


def test_job_passes_the_services_through(on: Adapters, sink: ListSink) -> None:
    from supervisor.jobs import inventory as job

    out = job.run(on, on.settings, FixtureWorkspaceReader.from_file(V2))
    assert out["autoregister"]["created"] == 3  # the job builds its own services


def test_autonomy_proposal_is_copied_only_when_the_column_exists(
    on: Adapters, sink: ListSink, monkeypatch: pytest.MonkeyPatch
) -> None:
    from supervisor.governance import model as governance_model
    from supervisor.inventory.autoregister import _copy_autonomy
    from supervisor.inventory.model import Node

    systems, _ = _services(on, sink)
    node = Node(
        "system",
        "app:x",
        attrs={"autonomy_level_proposal": {"level": "l3_tool_using_supervised"}},
    )
    _copy_autonomy(systems, "sys_none", node)  # no column in this branch: no error, no change

    class FakeState:
        class model:  # noqa: N801
            @staticmethod
            def table(name: str) -> Any:
                return type("T", (), {"column_names": ["system_id", "autonomy_level"]})()

    calls: list[Any] = []

    class FakeSystems:
        state = FakeState()

        def update_fields(self, sid: str, changes: Any, actor: str) -> None:
            calls.append((sid, changes, actor))

    _copy_autonomy(FakeSystems(), "sys_1", node)
    assert calls == []  # the column is not editable on this branch (EDITABLE lacks it)
    monkeypatch.setattr(
        governance_model, "EDITABLE", (*governance_model.EDITABLE, "autonomy_level")
    )
    _copy_autonomy(FakeSystems(), "sys_1", node)  # goes through update_fields: a chain record
    assert calls == [("sys_1", {"autonomy_level": "l3_tool_using_supervised"}, "workspace_scan")]


def test_link_failure_archives_the_draft(on: Adapters, sink: ListSink) -> None:
    systems, tasks = _services(on, sink)

    def boom(*a: Any, **k: Any) -> Any:
        raise RuntimeError("link failed")

    systems.link = boom  # type: ignore[method-assign]
    out = InventoryService.from_adapters(on).refresh_workspace(
        FixtureWorkspaceReader.from_file(V2), None, systems, tasks
    )
    assert out["autoregister"]["created"] == 0 and out["autoregister"]["errors"] == 3
    rows = on.state.query("ai_system")
    assert rows and {r["status"] for r in rows} == {"archived"}  # no live unlinked draft
    assert on.state.query("task") == []

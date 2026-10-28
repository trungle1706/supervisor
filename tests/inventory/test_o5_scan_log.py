"""WP-O5: the workspace scan writes one agent log row (step scan, by rule) when a node becomes an
unmanaged candidate, once per change of status, and nothing with ONBOARD_POSTDEPLOY off."""

from __future__ import annotations

import pytest

from supervisor.adapters.factory import Adapters
from supervisor.adapters.workspace.fixtures import FixtureWorkspaceReader
from supervisor.cases.service import CaseService
from supervisor.inventory.service import InventoryService


def _rows(a: Adapters) -> list[dict]:
    return [dict(r) for r in a.tables.query("onboard_log", {"step": "scan"})]


def test_off_writes_nothing(
    adapters: Adapters,
    svc: InventoryService,
    reader: FixtureWorkspaceReader,
    cases: CaseService,
) -> None:
    assert adapters.settings.onboard_postdeploy is False
    svc.fill_manifests()
    svc.refresh_workspace(reader, cases)
    assert _rows(adapters) == []


def test_each_new_candidate_gets_one_row_once(
    adapters: Adapters,
    svc: InventoryService,
    reader: FixtureWorkspaceReader,
    cases: CaseService,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(adapters.settings, "onboard_postdeploy", True)
    svc.fill_manifests()
    svc.refresh_workspace(reader, cases)
    rows = _rows(adapters)
    # the 7-item fixture has three unmanaged items; two are Apps, the third is a plain model
    # endpoint (no agent), which is no candidate kind
    assert len(rows) == 2
    assert all((r["by_kind"], r["actor"]) == ("rule", "rule") for r in rows)
    unmanaged = {r["node_id"] for r in svc.unmanaged()}
    assert {r["node_id"] for r in rows} < unmanaged  # a strict subset: the endpoint is not logged
    assert all(
        "candidate" in r["what"] and r["pointer"].startswith("inventory node ") for r in rows
    )
    # the names of the items are not copied into the log
    blob = " ".join(r["what"] + r["pointer"] for r in rows)
    for name in ("loan-bot-sandbox", "hr-chat-assistant", "adhoc-llama-endpoint"):
        assert name not in blob
    # more scans: the status does not change again, so no new row
    svc.refresh_workspace(reader, cases)
    svc.refresh_workspace(reader, cases)
    assert len(_rows(adapters)) == 2

"""Scheduler job, CLI, exports, onboarding hook, read API, flag-off behaviour."""

from __future__ import annotations

import csv
import io
import json
from pathlib import Path
from types import SimpleNamespace

from supervisor.adapters.llm.mock import MockChat
from supervisor.adapters.workspace.fixtures import FixtureWorkspaceReader
from supervisor.config import load_settings
from supervisor.inventory import __main__ as cli
from supervisor.inventory.read import inventory_for_agent
from supervisor.inventory.service import EDGE_CSV, NODE_CSV, InventoryService, _cell
from supervisor.jobs import inventory as job
from supervisor.onboard.run import run_onboarding
from tests.conftest import REPO_ROOT
from tests.inventory.conftest import WORKSPACE_7


def test_flag_default_off_and_job_schedule(tmp_path: Path) -> None:
    s = load_settings(sql_backend="sqlite", data_dir=tmp_path / "d", llm_base_url="")
    assert s.inventory_enabled is False and not job.scheduled(s)
    on = load_settings(
        sql_backend="sqlite", data_dir=tmp_path / "d", llm_base_url="", inventory_enabled=True
    )
    assert not job.scheduled(on)  # laptop without a fixture: nothing to scan
    app = load_settings(
        supervisor_mode="databricks_app",
        sql_backend="sqlite",
        data_dir=tmp_path / "d",
        llm_base_url="",
        inventory_enabled=True,
    )
    assert job.scheduled(app) and app.sched_inventory_s == 3600
    fx = load_settings(
        sql_backend="sqlite",
        data_dir=tmp_path / "d",
        llm_base_url="",
        inventory_enabled=True,
        inventory_workspace_fixture=WORKSPACE_7,
    )
    assert job.scheduled(fx)


def test_scheduler_lists_the_job_only_when_on(adapters, sink) -> None:
    from supervisor.monitors.common import MonitorContext
    from supervisor.scheduler import build_jobs

    runtime = SimpleNamespace(adapters=adapters, chain=sink, settings=adapters.settings)
    ctx = MonitorContext.from_adapters(adapters, sink)
    jobs = {j.name: j for j in build_jobs(adapters.settings, runtime, ctx)}
    assert "inventory" not in jobs  # laptop without a fixture: nothing to scan
    adapters.settings.inventory_workspace_fixture = WORKSPACE_7
    jobs = {j.name: j for j in build_jobs(adapters.settings, runtime, ctx)}
    assert jobs["inventory"].enabled is True and jobs["inventory"].interval_s == 3600
    out = jobs["inventory"].fn()  # what the scheduler tick calls
    assert out["shadow"]["unmanaged"] == 3 and out["shadow"]["cases_opened_or_found"] == 3


def test_job_run_fills_and_reports(adapters, cases) -> None:
    reader = FixtureWorkspaceReader.from_file(WORKSPACE_7)
    out = job.run(adapters, adapters.settings, reader, cases)
    assert out["shadow"]["unmanaged"] == 3 and out["manifests"]["nodes_new"] > 0
    assert out["errors"] == {}
    again = job.run(adapters, adapters.settings, reader, cases)
    assert again["apply"]["nodes_new"] == 0 and again["manifests"]["nodes_new"] == 0


def test_exports_json_and_csv_pair(svc: InventoryService, tmp_path: Path) -> None:
    svc.fill_manifests()
    svc.refresh_workspace(FixtureWorkspaceReader.from_file(WORKSPACE_7))
    paths = svc.write_exports(tmp_path / "out")
    assert [p.name for p in paths] == [
        "inventory.json",
        "inventory_nodes.csv",
        "inventory_edges.csv",
    ]
    doc = json.loads(paths[0].read_text(encoding="utf-8"))
    nodes = list(csv.DictReader(io.StringIO(paths[1].read_text(encoding="utf-8"))))
    edges = list(csv.DictReader(io.StringIO(paths[2].read_text(encoding="utf-8"))))
    assert tuple(nodes[0]) == NODE_CSV and tuple(edges[0]) == EDGE_CSV
    assert len(nodes) == len(doc["nodes"]) == 34 and len(edges) == len(doc["edges"]) == 34
    ids = {n["node_id"] for n in nodes}
    assert all(e["src_id"] in ids and e["dst_id"] in ids for e in edges)
    assert {n["display_name"] for n in nodes if n["status"] == "unmanaged"} == {
        "loan-bot-sandbox",
        "hr-chat-assistant",
        "adhoc-llama-endpoint",
    }
    assert svc.export_json() == doc  # deterministic
    assert _cell("=HYPERLINK(1)") == "'=HYPERLINK(1)" and _cell(None) == ""


def test_cli_manifests_show_export(monkeypatch, tmp_path: Path, capsys) -> None:
    monkeypatch.setenv("INVENTORY_ENABLED", "1")
    monkeypatch.setenv("SQL_BACKEND", "sqlite")
    monkeypatch.setenv("LLM_BASE_URL", "")
    assert cli.main(["manifests"]) == 0
    assert cli.main(["show", "payments"]) == 0
    out = capsys.readouterr().out
    assert "[OK] manifests" in out and "tool:transfer risk=critical" in out
    assert out.isascii()
    assert cli.main(["show", "nobody"]) == 1
    assert cli.main(["export", "--out", str(tmp_path / "x")]) == 0
    assert (tmp_path / "x" / "inventory_nodes.csv").is_file()


def test_cli_is_a_noop_when_off(monkeypatch, capsys) -> None:
    monkeypatch.delenv("INVENTORY_ENABLED", raising=False)
    assert cli.main(["manifests"]) == 0
    assert "[SKIP]" in capsys.readouterr().out


def test_read_api_for_advisor_and_launch(adapters, svc: InventoryService) -> None:
    svc.fill_manifests()
    info = inventory_for_agent(adapters, "payments")
    assert info is not None and info["found"]
    assert info["effective_risk"] == "critical"
    assert [x["name"] for x in info["links"]["uses:model_endpoint"]] == ["qwen3:4b"]
    assert all(x["evidence_ref"] for ls in info["links"].values() for x in ls)
    adapters.settings.inventory_enabled = False
    assert inventory_for_agent(adapters, "payments") is None  # off: the advisor sees nothing


def test_onboarding_hook_fills_when_on_and_not_when_off(tmp_path: Path) -> None:
    loan = REPO_ROOT / "data" / "corpus" / "repos" / "langgraph_loan_triage"
    for on in (True, False):
        base = tmp_path / ("on" if on else "off")
        s = load_settings(
            sql_backend="sqlite", data_dir=base / "data", llm_base_url="", inventory_enabled=on
        )
        res = run_onboarding(
            loan, base / "out", settings=s, chat=MockChat(model_id="mock-onboarding-v1")
        )
        assert ("[OK] inventory:" in "\n".join(res.lines)) is on
        from supervisor.adapters.factory import build_adapters

        a = build_adapters(s)
        try:
            n = len(a.state.query("inventory_node"))
        finally:
            a.close()
        assert (n > 0) is on

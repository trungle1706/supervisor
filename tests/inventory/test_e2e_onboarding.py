"""E2E: run the real onboarding on the sample loan-triage repo, then fill the inventory from the
``inventory.json`` it wrote (no hand-made input)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from supervisor.adapters.llm.mock import MockChat
from supervisor.adapters.workspace.fixtures import FixtureWorkspaceReader
from supervisor.config import load_settings
from supervisor.inventory.service import InventoryService
from supervisor.onboard.run import run_onboarding
from tests.conftest import REPO_ROOT

LOAN = REPO_ROOT / "data" / "corpus" / "repos" / "langgraph_loan_triage"


@pytest.fixture(scope="module")
def onboarding_out(tmp_path_factory: pytest.TempPathFactory) -> Path:
    base = tmp_path_factory.mktemp("onb")
    settings = load_settings(sql_backend="sqlite", data_dir=base / "data", llm_base_url="")
    out = base / "out"
    run_onboarding(LOAN, out, settings=settings, chat=MockChat(model_id="mock-onboarding-v1"))
    return out


def test_inventory_from_real_onboarding_output(
    onboarding_out: Path, svc: InventoryService, adapters
) -> None:
    path = onboarding_out / "inventory.json"
    assert path.is_file()
    raw = json.loads(path.read_text(encoding="utf-8"))
    assert raw["agent_id"] == "langgraph_loan_triage"
    res = svc.fill_onboarding(path)
    assert res.nodes_new > 0 and res.edges_dropped == 0
    view = svc.agent_view("langgraph_loan_triage")
    assert view is not None
    by_kind: dict[str, set[str]] = {}
    for n in view["nodes"]:
        by_kind.setdefault(n["kind"], set()).add(n["display_name"])
    assert by_kind["tool"] == {
        "get_bureau_score",
        "read_loan_application",
        "record_preapproval_decision",
    }
    assert by_kind["model_endpoint"] == {"databricks-meta-llama-3-3-70b-instruct"}
    assert by_kind["dataset"] == {"bureau_scores", "loan_applications"}
    # a production agent resolves to its endpoint, tools and data, each with file:line evidence
    refs = {e["evidence_ref"] for e in view["edges"]}
    assert {"tools.py:46", "graph.py:17", "tools.py:37", "tools.py:52"} <= refs
    assert all(":" in r for r in refs)
    root = next(n for n in view["nodes"] if n["node_id"] == view["root"])
    assert root["effective_risk"] == "high"  # credit tool passes up; no declared tier
    assert root["own_risk"] is None and root["decision33_class"] is None
    assert "tool:record_preapproval_decision risk=high" in view["tree"]
    # idempotent
    again = svc.fill_onboarding(path)
    assert again.nodes_new == 0 and again.edges_new == 0


def test_bare_table_names_resolve_to_uc_tables(onboarding_out: Path, svc: InventoryService) -> None:
    data = {
        "tables": {"main.lending": ["loan_applications", "bureau_scores", "other"]},
    }
    svc.refresh_workspace(FixtureWorkspaceReader(data))
    svc.fill_onboarding(onboarding_out / "inventory.json")
    view = svc.agent_view("langgraph_loan_triage")
    assert view is not None
    names = {n["name"] for n in view["nodes"] if n["kind"] == "dataset"}
    assert names == {"main.lending.loan_applications", "main.lending.bureau_scores"}


def test_summary_for_advisor_and_launch(onboarding_out: Path, svc: InventoryService) -> None:
    svc.fill_onboarding(onboarding_out / "inventory.json")
    s = svc.summary_for_agent("langgraph_loan_triage")
    assert s["found"] and s["effective_risk"] == "high"
    assert [x["name"] for x in s["links"]["uses:tool"]] == [
        "get_bureau_score",
        "read_loan_application",
        "record_preapproval_decision",
    ]
    assert svc.summary_for_agent("nope") == {"agent_id": "nope", "found": False}

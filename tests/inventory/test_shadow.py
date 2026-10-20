"""Workspace filler and shadow-AI check on the 7-item fixture workspace."""

from __future__ import annotations

import json

from supervisor.adapters.workspace.fixtures import FixtureWorkspaceReader
from supervisor.cases.service import CaseService
from supervisor.inventory import shadow
from supervisor.inventory.service import InventoryService
from tests.conftest import REPO_ROOT

UNMANAGED = {"loan-bot-sandbox", "hr-chat-assistant", "adhoc-llama-endpoint"}


def _status(svc: InventoryService) -> dict[str, str]:
    out = {}
    for r in svc.state.query("inventory_node"):
        attrs = r["attrs"]
        if attrs.get("workspace_kind") in ("app", "serving_endpoint"):
            out[r["display_name"]] = r["status"]
    return out


def test_fixture_has_seven_items(reader: FixtureWorkspaceReader) -> None:
    assert len(reader.list_apps()) + len(reader.list_serving_endpoints()) == 7


def test_shadow_scan_classifies_the_seven_items(
    svc: InventoryService, reader: FixtureWorkspaceReader, cases: CaseService
) -> None:
    svc.fill_manifests()
    out = svc.refresh_workspace(reader, cases)
    assert out["errors"] == {}
    assert out["shadow"] == {
        "managed": 3,
        "allowlisted": 1,
        "unmanaged": 3,
        "cases_opened_or_found": 3,
    }
    st = _status(svc)
    assert {k for k, v in st.items() if v == "unmanaged"} == UNMANAGED
    assert st["bi-portal"] == "allowlisted"
    assert st["payments"] == st["credit-prequal"] == st["qwen3:4b"] == "active"
    rows = svc.unmanaged()
    assert {r["display_name"] for r in rows} == UNMANAGED
    assert all(r["case_id"] for r in rows)


def test_cases_are_low_severity_and_deduped(
    svc: InventoryService, reader: FixtureWorkspaceReader, cases: CaseService, sink
) -> None:
    svc.fill_manifests()
    svc.refresh_workspace(reader, cases)
    first = {c["case_id"]: c for c in cases.list_cases()}
    assert len(first) == 3
    assert {c["severity"] for c in first.values()} == {"low"}
    assert {c["agent_id"] for c in first.values()} == {shadow.CASE_AGENT_ID}
    n_records = len(sink.records)
    for _ in range(3):  # three more refreshes: still three cases, no new evidence records
        svc.refresh_workspace(reader, cases)
    assert {c["case_id"] for c in cases.list_cases()} == set(first)
    assert len(sink.records) == n_records
    # closing a case does not open a second one for the same node
    from supervisor.adapters.auth.dev_header import DevHeaderPrincipal

    me = DevHeaderPrincipal.from_file(REPO_ROOT / "config" / "users.yaml").users["reviewer.an"]
    cid = next(iter(first))
    c = cases.assign(cid, me.user_id, me, first[cid]["row_version"])
    cases.transition(cid, "triaged", me, c["row_version"], note="checked")
    svc.refresh_workspace(reader, cases)
    assert len(cases.list_cases()) == 3


def test_workspace_refill_is_idempotent(
    svc: InventoryService, reader: FixtureWorkspaceReader
) -> None:
    svc.fill_manifests()
    svc.refresh_workspace(reader)
    n, e = len(svc.state.query("inventory_node")), len(svc.state.query("inventory_edge"))
    v = {r["node_id"]: r["row_version"] for r in svc.state.query("inventory_node")}
    svc.refresh_workspace(reader)
    assert (len(svc.state.query("inventory_node")), len(svc.state.query("inventory_edge"))) == (
        n,
        e,
    )
    assert v == {r["node_id"]: r["row_version"] for r in svc.state.query("inventory_node")}


def test_no_cases_without_a_case_service(svc: InventoryService, reader) -> None:
    svc.fill_manifests()
    out = svc.refresh_workspace(reader, None)
    assert out["shadow"]["unmanaged"] == 3 and out["shadow"]["cases_opened_or_found"] == 0


def test_workspace_objects_become_nodes_with_evidence(
    svc: InventoryService, reader: FixtureWorkspaceReader
) -> None:
    svc.fill_manifests()
    svc.refresh_workspace(reader)
    g = svc.store.load_graph()
    ds = g.by_name("dataset", "main.lending.bureau_scores")
    assert ds is not None
    assert {
        "source": "workspace_scan",
        "ref": "workspace:uc-table/main.lending.bureau_scores",
    } in ds.evidence
    rm = g.by_name("model", "main.ml.fraud_scorer")
    assert rm is not None and rm.attrs["workspace_kind"] == "registered_model"
    ep = g.by_name("model_endpoint", "adhoc-llama-endpoint")
    assert ep is not None
    served = [g.nodes[e.dst_id].name for e in g.out_edges(ep.node_id, ("serves",))]
    assert served == ["main.ml.adhoc_llama"]
    # lineage: payments reads bureau_scores, with workspace evidence
    view = svc.agent_view("payments")
    assert view is not None
    reads = [e for e in view["edges"] if e["kind"] == "reads"]
    assert reads and reads[0]["source"] == "workspace_scan"
    # the managed app is linked to its agent, the shadow app is not
    hosted = {
        g.nodes[e.dst_id].display_name
        for e in g.edges.values()
        if e.kind == "hosted_on" and g.nodes[e.src_id].kind == "system"
    }
    assert {"payments", "credit-prequal"} <= hosted and "loan-bot-sandbox" not in hosted


def test_item_that_disappears_is_gone_and_leaves_the_count(
    svc: InventoryService, reader: FixtureWorkspaceReader, tmp_path
) -> None:
    svc.fill_manifests()
    svc.refresh_workspace(reader)
    data = json.loads((REPO_ROOT / "tests/fixtures/inventory/workspace_7.json").read_text())
    data["apps"] = [a for a in data["apps"] if a["name"] != "hr-chat-assistant"]
    svc.refresh_workspace(FixtureWorkspaceReader(data))
    st = _status(svc)
    assert st["hr-chat-assistant"] == "gone"
    assert {r["display_name"] for r in svc.unmanaged()} == UNMANAGED - {"hr-chat-assistant"}
    # it comes back: unmanaged again, and still the same single case
    svc.refresh_workspace(reader)
    assert _status(svc)["hr-chat-assistant"] == "unmanaged"


def test_failed_listing_does_not_mark_objects_gone(
    svc: InventoryService, reader: FixtureWorkspaceReader
) -> None:
    svc.fill_manifests()
    svc.refresh_workspace(reader)

    class Broken(FixtureWorkspaceReader):
        def list_apps(self):  # noqa: ANN201
            raise RuntimeError("workspace unavailable")

    out = svc.refresh_workspace(Broken(reader.data))
    assert out["errors"] == {"app": "RuntimeError"}  # class name only, never the message
    st = _status(svc)
    assert st["hr-chat-assistant"] == "unmanaged" and st["loan-bot-sandbox"] == "unmanaged"


def test_registering_an_agent_clears_the_shadow_flag(
    svc: InventoryService, reader: FixtureWorkspaceReader, cases: CaseService
) -> None:
    svc.fill_manifests()
    svc.refresh_workspace(reader, cases)
    inv = {"agent_id": "loan-bot-sandbox", "name": "Loan bot", "owner_team": "Lending"}
    svc.fill_onboarding(inv)
    svc.refresh_workspace(reader, cases)
    assert _status(svc)["loan-bot-sandbox"] == "active"
    assert {r["display_name"] for r in svc.unmanaged()} == UNMANAGED - {"loan-bot-sandbox"}


def test_self_app_and_placeholder_allowlist(svc: InventoryService, reader) -> None:
    svc.settings.inventory_self_app = "hr-chat-assistant"
    svc.fill_manifests()
    svc.refresh_workspace(reader)
    assert _status(svc)["hr-chat-assistant"] == "allowlisted"
    p = REPO_ROOT / "config" / "inventory_allowlist.yaml"
    al = shadow.Allowlist.load(p)
    assert al.apps == [] and al.serving_endpoints == []  # FILL-ME entries never match
    assert not al.matches("app", "FILL-ME-known-non-agent-app-name")


def test_baseline_counts(svc: InventoryService, reader: FixtureWorkspaceReader, cases) -> None:
    """Regression baseline (2026-10-20, bf3a23a + WP24): graph size after manifests + fixture."""
    svc.fill_manifests()
    svc.refresh_workspace(reader, cases)
    base = json.loads(
        (REPO_ROOT / "tests/fixtures/inventory/baseline_counts.json").read_text(encoding="utf-8")
    )["manifests_plus_workspace_7"]
    nodes = svc.state.query("inventory_node")
    active_edges = [e for e in svc.state.query("inventory_edge") if e["active"]]
    assert len(nodes) == base["nodes"] and len(active_edges) == base["edges"]
    c = svc.counts()
    assert c["unmanaged"] == base["unmanaged"]

"""WP-G3 scan sources v2: MLflow model versions, served entities, Genie spaces, jobs that name an
LLM endpoint, Vector Search indexes, UC functions and MCP connections. Fakes only; no network."""

from __future__ import annotations

import json
from types import SimpleNamespace
from typing import Any

import pytest

from supervisor.adapters.workspace.databricks_sdk import DatabricksWorkspaceReader
from supervisor.adapters.workspace.fixtures import FixtureWorkspaceReader
from supervisor.inventory import shadow
from supervisor.inventory.fill import fill_from_workspace
from supervisor.inventory.model import NODE_KINDS
from supervisor.inventory.service import InventoryService
from tests.conftest import REPO_ROOT

V2 = REPO_ROOT / "tests" / "fixtures" / "inventory" / "workspace_v2.json"


@pytest.fixture
def v2() -> FixtureWorkspaceReader:
    return FixtureWorkspaceReader.from_file(V2)


def _by_kind(svc: InventoryService) -> dict[str, dict[str, Any]]:
    out: dict[str, dict[str, Any]] = {}
    for r in svc.state.query("inventory_node"):
        out.setdefault(r["kind"], {})[r["display_name"]] = r
    return out


def test_new_node_kinds_exist() -> None:
    for k in ("genie_space", "job", "vector_index", "uc_function"):
        assert k in NODE_KINDS


def test_v2_fixture_fills_every_source(svc: InventoryService, v2: FixtureWorkspaceReader) -> None:
    out = svc.refresh_workspace(v2)
    assert out["errors"] == {}
    kinds = _by_kind(svc)
    assert set(kinds["genie_space"]) == {"Lending analytics", "Known BI space"}
    assert set(kinds["job"]) == {
        "nightly-memo-batch"
    }  # the job without an LLM endpoint is left out
    assert set(kinds["vector_index"]) == {"main.lending.policy_index"}
    assert set(kinds["uc_function"]) == {
        "main.lending.lookup_applicant",
        "main.lending.get_exposure",
    }
    assert set(kinds["mcp_server"]) == {"mcp_core_banking"}  # only the MCP connection
    model = kinds["model"]["main.ml.credit_memo_agent"]
    assert model["attrs"]["versions_n"] == 2
    assert model["attrs"]["latest_version"] == "4"
    assert model["attrs"]["aliases"] == ["champion"]
    refs = {e["ref"] for e in model["evidence"]}
    assert "workspace:registered-model/main.ml.credit_memo_agent" in refs
    assert "workspace:model-version/main.ml.credit_memo_agent/4" in refs
    agent_ep = kinds["model_endpoint"]["agent-credit-memo"]
    assert agent_ep["attrs"]["agent_endpoint"] is True
    gw = kinds["model_endpoint"]["gpt-gateway"]
    assert gw["attrs"]["external_providers"] == ["openai"]
    assert "openai" in {r["display_name"] for r in kinds["supplier"].values()}
    job = kinds["job"]["nightly-memo-batch"]
    assert job["attrs"]["llm_endpoints"] == ["gpt-gateway"]
    assert {"source": "workspace_scan", "ref": "workspace:job/nightly-memo-batch"} in job[
        "evidence"
    ]


def test_v2_edges_and_refs(svc: InventoryService, v2: FixtureWorkspaceReader) -> None:
    svc.refresh_workspace(v2)
    g = svc.store.load_graph()
    edges = {
        (g.nodes[e.src_id].display_name, e.kind, g.nodes[e.dst_id].display_name): e.evidence_ref
        for e in g.edges.values()
        if e.source == "workspace_scan"
    }
    assert edges[("nightly-memo-batch", "uses", "gpt-gateway")] == (
        "workspace:job/nightly-memo-batch/task/score"
    )
    assert edges[("Lending analytics", "reads", "main.lending.loan_applications")] == (
        "workspace:genie-space/Lending analytics"
    )
    assert ("main.lending.policy_index", "reads", "main.lending.loan_applications") in edges
    assert ("agent-credit-memo", "serves", "main.ml.credit_memo_agent") in edges
    assert ("gpt-4o", "owned_by", "openai") in edges


def test_nothing_in_the_graph_looks_like_a_url_or_workspace_id(
    svc: InventoryService, v2: FixtureWorkspaceReader
) -> None:
    svc.refresh_workspace(v2)
    dump = json.dumps(svc.export_json())
    assert "http" not in dump and "dbc-" not in dump and "adb-" not in dump


def test_refill_is_idempotent_and_removed_objects_go(
    svc: InventoryService, v2: FixtureWorkspaceReader
) -> None:
    svc.refresh_workspace(v2)
    first = svc.counts()
    svc.refresh_workspace(v2)
    assert svc.counts() == first
    data = dict(v2.data)
    data["genie_spaces"] = [data["genie_spaces"][0]]
    data["connections"] = []
    data["jobs"] = []
    svc.refresh_workspace(FixtureWorkspaceReader(data))
    kinds = _by_kind(svc)
    assert kinds["genie_space"]["Known BI space"]["status"] == "gone"
    assert kinds["mcp_server"]["mcp_core_banking"]["status"] == "gone"
    assert kinds["job"]["nightly-memo-batch"]["status"] == "gone"


def test_one_failed_listing_is_reported_and_marks_nothing_gone(
    svc: InventoryService, v2: FixtureWorkspaceReader
) -> None:
    svc.refresh_workspace(v2)

    class Broken(FixtureWorkspaceReader):
        def list_genie_spaces(self) -> list[dict[str, Any]]:
            raise PermissionError("no access")

    out = svc.refresh_workspace(Broken(v2.data))
    assert out["errors"] == {"genie_space": "PermissionError"}
    kinds = _by_kind(svc)
    assert {n["status"] for n in kinds["genie_space"].values()} != {"gone"}
    assert "nightly-memo-batch" in kinds["job"]


def test_reader_without_v2_methods_is_not_an_error() -> None:
    class Old:
        def list_serving_endpoints(self) -> list[dict[str, Any]]:
            return []

        def list_registered_models(self) -> list[dict[str, Any]]:
            return []

    scan = fill_from_workspace(Old(), schemas=[])
    assert scan.errors.get("genie_space") is None and "genie_space" not in scan.ok
    assert scan.errors.get("uc_function") is None and "uc_function" not in scan.ok


def test_genie_space_is_unmanaged_unless_allowlisted(
    svc: InventoryService, v2: FixtureWorkspaceReader
) -> None:
    svc.refresh_workspace(v2)
    g = svc.store.load_graph()
    allow = shadow.Allowlist(genie_spaces=["known bi*"])
    verdict = shadow.classify(g, allow)
    by_name = {g.nodes[nid].display_name: v for nid, v in verdict.items()}
    assert by_name["Lending analytics"] == "unmanaged"
    assert by_name["Known BI space"] == "allowlisted"
    assert by_name["agent-credit-memo"] == "unmanaged"  # an agent endpoint nobody registered
    assert by_name["loan-copilot"] == "unmanaged"


# ----------------------------------------------------------------------- SDK reader (fake client)


def _ns(**kw: Any) -> SimpleNamespace:
    return SimpleNamespace(**kw)


def _client() -> SimpleNamespace:
    """Only the read calls exist on the fake: any create/update/delete call would raise."""
    ent_custom = _ns(
        entity_name="main.ml.agent", entity_version=7, foundation_model=None, external_model=None
    )
    ent_ext = _ns(
        foundation_model=None,
        external_model=_ns(name="gpt-4o", provider=_ns(value="openai")),
        entity_name=None,
    )
    endpoints = [
        _ns(
            name="agent-ep",
            task="agent/v1/chat",
            state=_ns(ready=_ns(value="READY")),
            config=_ns(served_entities=[ent_custom]),
            tags=[],
        ),
        _ns(
            name="ext-ep",
            task="llm/v1/chat",
            state=None,
            config=_ns(served_entities=[ent_ext]),
            tags=[_ns(key="agent", value="1")],
        ),
    ]
    jobs = [
        _ns(
            settings=_ns(
                name="batch",
                tasks=[
                    _ns(
                        task_key="nb",
                        notebook_task=_ns(base_parameters={"endpoint": "ext-ep", "n": 3}),
                        spark_python_task=None,
                        python_wheel_task=None,
                    ),
                    _ns(
                        task_key="whl",
                        notebook_task=None,
                        spark_python_task=None,
                        python_wheel_task=_ns(
                            parameters=["--ep", "agent-ep"], named_parameters={"k": "v"}
                        ),
                    ),
                ],
                parameters=[_ns(name="p", default="x")],
            )
        )
    ]
    return _ns(
        apps=_ns(list=lambda: []),
        tables=_ns(list=lambda catalog_name, schema_name: []),
        serving_endpoints=_ns(list=lambda: endpoints),
        registered_models=_ns(list=lambda: [_ns(full_name="main.ml.agent", name="agent")]),
        model_versions=_ns(
            list=lambda full_name: [
                _ns(version=1, aliases=[]),
                _ns(version=2, aliases=[_ns(alias_name="champion")]),
            ]
        ),
        model_registry=_ns(
            list_models=lambda: [_ns(name="old")],
            search_model_versions=lambda filter: [_ns(version="5", current_stage="Production")],
        ),
        genie=_ns(list_spaces=lambda: _ns(spaces=[_ns(space_id="01ef", title="Credit Q&A")])),
        jobs=_ns(list=lambda expand_tasks: jobs),
        vector_search_endpoints=_ns(list_endpoints=lambda: [_ns(name="vs1")]),
        vector_search_indexes=_ns(
            list_indexes=lambda endpoint_name: [
                _ns(name="main.s.idx", index_type=_ns(value="DELTA_SYNC"))
            ],
            get_index=lambda index_name: _ns(delta_sync_index_spec=_ns(source_table="main.s.docs")),
        ),
        functions=_ns(
            list=lambda catalog_name, schema_name: [_ns(full_name="main.s.fn", name="fn")]
        ),
        connections=_ns(
            list=lambda: [
                _ns(
                    name="mcp1",
                    connection_type=_ns(value="HTTP"),
                    options={"host": "https://x.invalid", "is_mcp_connection": "true"},
                ),
                _ns(name="db1", connection_type=_ns(value="MYSQL"), options={"host": "h"}),
            ]
        ),
    )


def test_sdk_reader_v2_calls_with_fake_client() -> None:
    r = DatabricksWorkspaceReader(_client())
    eps = {e["name"]: e for e in r.list_serving_endpoints()}
    assert eps["agent-ep"]["agent"] is True
    assert eps["agent-ep"]["entities"] == [
        {"kind": "custom_model", "name": "main.ml.agent", "version": "7"}
    ]
    assert eps["ext-ep"]["agent"] is True  # by tag
    assert eps["ext-ep"]["entities"] == [
        {"kind": "external_model", "name": "gpt-4o", "provider": "openai"}
    ]
    assert r.list_model_versions() == [
        {"model": "main.ml.agent", "version": "2", "aliases": ["champion"], "registry": "uc"},
        {"model": "main.ml.agent", "version": "1", "aliases": [], "registry": "uc"},
        {"model": "old", "version": "5", "stage": "Production", "registry": "workspace"},
    ]
    assert r.list_genie_spaces() == [{"name": "Credit Q&A", "tables": []}]
    jobs = r.list_jobs()
    assert jobs[0]["name"] == "batch"
    assert jobs[0]["tasks"][0] == {"key": "nb", "kind": "notebook", "values": ["ext-ep", "3"]}
    assert jobs[0]["tasks"][1]["values"] == ["--ep", "agent-ep", "v"]
    assert r.list_vector_indexes() == [
        {"name": "main.s.idx", "type": "DELTA_SYNC", "source_table": "main.s.docs"}
    ]
    assert r.list_functions("main", "s") == ["main.s.fn"]
    conns = r.list_connections()
    assert conns == [
        {"name": "mcp1", "type": "HTTP", "mcp": True},
        {"name": "db1", "type": "MYSQL", "mcp": False},
    ]
    assert "x.invalid" not in json.dumps(conns)  # options never leave the reader


def test_sdk_reader_v2_feeds_the_scan_without_ids_or_urls() -> None:
    scan = fill_from_workspace(DatabricksWorkspaceReader(_client()), schemas=["main.s"])
    assert scan.errors == {}
    dump = json.dumps(
        [(n.kind, n.name, n.attrs, n.evidence) for n in scan.graph.nodes.values()], default=str
    )
    assert "01ef" not in dump and "x.invalid" not in dump
    kinds = {n.kind for n in scan.graph.nodes.values()}
    assert {"genie_space", "job", "vector_index", "uc_function", "mcp_server"} <= kinds

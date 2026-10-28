"""WP-O2: the register workflow v2 prefill reads the facts card of the node (ONBOARD_FACTS).

With facts: purpose, data, model family, money / credit tools, human control and autonomy come from
the fact rows, each with a reason key ``rg2_why_fact_*`` and the pointer of the fact. Without facts
(or with the flag off) the prefill is the one of WP-N3."""

from __future__ import annotations

import io
import re
import zipfile
from typing import Any

import pytest

from supervisor.governance.register_v2 import service as rs
from supervisor.governance.register_v2 import suggest
from supervisor.inventory.store import InventoryStore
from supervisor.onboard.facts import FactsService
from supervisor.onboard.intake import IntakeService

from .conftest import Console
from .test_n3_register import ME, new, reg, seed_node  # noqa: F401  (fixture)

MANIFEST = """id: helper
name: Synthetic helper
version: 0.1.0
owner: team-demo
description: Answers staff questions about synthetic fees.
model_id: qwen3.8-27b-int4
tools:
  - name: get_fee
    risk_class: read_only
  - name: refund_fee
    risk_class: credit
"""
AGENT = """import httpx
def get_fee(account_id):
    return spark.sql("SELECT fee FROM main.synthetic.fees WHERE account_id = 1")
def refund_fee(account_id, amount_minor):
    return httpx.post("https://llm.example.invalid/v1/chat/completions", json={})
"""


def build_facts(c: Console, node_id: str) -> None:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("manifest.yaml", MANIFEST)
        zf.writestr("agent.py", AGENT)
    s = c.ctx.settings
    n = IntakeService(s, c.ctx.state, c.ctx.clock).submit_zip(node_id, buf.getvalue(), "s.zip", ME)[
        "n"
    ]
    FactsService(s, c.ctx.state, c.ctx.clock).build(node_id, n)


@pytest.fixture
def facts_on(reg: Console, monkeypatch: pytest.MonkeyPatch) -> Console:  # noqa: F811
    monkeypatch.setattr(reg.ctx.settings, "onboard_intake", True)
    monkeypatch.setattr(reg.ctx.settings, "onboard_facts", True)
    return reg


def sg_of(c: Console, did: str) -> dict[str, Any]:
    return rs.store_of(c.ctx).get(did, ME)["data"]["sg"]


def test_prefill_uses_the_facts_with_reason_keys_and_pointers(facts_on: Console) -> None:
    nid = seed_node(facts_on)
    before = sg_of(facts_on, new(facts_on, f"?from={nid}"))
    assert before["money_movement"]["reason_key"] == "rg2_why_money_tool"  # the scan, no facts yet
    build_facts(facts_on, nid)
    did = new(facts_on, f"?from={nid}")
    sg = sg_of(facts_on, did)
    assert sg["purpose"]["reason_key"] == "rg2_why_fact_purpose"
    assert "Answers staff questions about synthetic fees" in sg["purpose"]["value"]
    assert "Tools: get_fee, refund_fee" in sg["purpose"]["value"]
    assert "Models: qwen3.8-27b-int4" in sg["purpose"]["value"]
    assert "Data: main.synthetic.fees" in sg["purpose"]["value"]
    assert re.search(r"claim:purpose @ manifest\.yaml:\d+", sg["purpose"]["fact"])
    assert sg["data_sources"]["value"] == "main.synthetic.fees"
    assert sg["data_sources"]["reason_key"] == "rg2_why_fact_data"
    assert re.search(r"dataset:main\.synthetic\.fees @ agent\.py:3", sg["data_sources"]["fact"])
    assert sg["model_family"]["value"] == "qwen" and sg["model_family"]["reason_key"] == (
        "rg2_why_fact_model"
    )
    assert sg["credit_decision"]["value"] is True
    assert sg["credit_decision"]["reason_key"] == "rg2_why_fact_tool_credit"
    assert sg["money_movement"]["value"] is False
    assert sg["money_movement"]["reason_key"] == "rg2_why_fact_tool_none"
    assert sg["autonomy_level"]["value"] == "l3_tool_using_supervised"
    assert sg["autonomy_level"]["reason_key"] == "rg2_why_fact_autonomy"
    assert all(v["source"] == "scan" for v in sg.values())
    # the page shows the reason and the pointer
    html = facts_on.get(f"/console/register/{did}/step/2?lang=en").text
    assert 'data-suggest="purpose"' in html and "facts card" in html and 'data-fact="1"' in html
    assert "agent.py:3" in html


def test_without_facts_or_with_the_flag_off_the_prefill_is_as_before(
    facts_on: Console, monkeypatch: pytest.MonkeyPatch
) -> None:
    nid = seed_node(facts_on)
    plain = sg_of(facts_on, new(facts_on, f"?from={nid}"))
    build_facts(facts_on, nid)
    monkeypatch.setattr(facts_on.ctx.settings, "onboard_facts", False)
    off = sg_of(facts_on, new(facts_on, f"?from={nid}"))
    # the flag is off: no suggestion names a fact. The edges that the build wrote stay in the
    # graph (they are data), so the scan text may count more tools than before.
    assert set(off) == set(plain)
    assert not [k for k, v in off.items() if "fact" in v or "rg2_why_fact" in v["reason_key"]]


def test_suggest_functions_are_pure(facts_on: Console) -> None:
    nid = seed_node(facts_on)
    graph = InventoryStore(facts_on.ctx.state, facts_on.ctx.clock).load_graph()
    node = graph.nodes[nid]
    assert suggest.from_node(graph, node, None, None) == suggest.from_node(graph, node, None, [])
    rows = [
        {
            "kind": "approval_point",
            "name": "human approval step",
            "detail": "x",
            "file": "a.py",
            "line": 4,
        }
    ]
    sg = suggest.from_node(graph, node, None, rows)
    assert sg["human_control"]["value"] == "pre_approval"
    assert sg["human_control"]["fact"] == "approval_point:human approval step @ a.py:4"

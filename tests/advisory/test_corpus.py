"""(a) report and patches for every corpus repo; (b) every patch applies and parses."""

from __future__ import annotations

import ast
import json
import shutil
from pathlib import Path

import pytest

from supervisor.advisory.integration.advise import Advice
from supervisor.advisory.integration.patchcheck import apply_patch
from supervisor.advisory.integration.render import render_html, render_json, render_md
from tests.advisory.conftest import REPOS, target_of


def test_corpus_has_twenty_one_repos() -> None:
    assert len(REPOS) == 21  # WP1b-B added fastapi_deepagents_credit_toy


@pytest.mark.parametrize("name", REPOS)
def test_report_and_patches(name: str, advices: dict[str, Advice]) -> None:
    advice = advices[name]
    r = advice.report
    assert r.agent_id and r.readiness.total == sum(a.points for a in r.readiness.areas)
    assert 0 <= r.readiness.total <= 100
    assert [a.weight for a in r.readiness.areas] == [20, 30, 15, 10, 10, 10, 5]
    kinds = [p.kind for p in advice.patches]
    assert "hook_module" in kinds and "policy" in kinds and "settings" in kinds
    assert [p.path for p in advice.patches] == [x.path for x in r.patches]
    text = render_json(r)
    assert text.endswith("\n") and json.loads(text)["agent_id"] == r.agent_id
    assert "/home/" not in text and str(target_of(name)) not in text
    for tool in r.found.tools:
        if tool.defined_at:
            assert not Path(tool.defined_at.split(":")[0]).is_absolute()
    n_gated = sum(1 for t in r.found.tools if t.risk_class != "read_only" or t.side_effects)
    assert len(r.needed.gate_sites) == n_gated
    assert render_md(r, "vi") and render_md(r, "en") and "<html" in render_html(r)


@pytest.mark.parametrize("name", REPOS)
def test_patches_apply_in_a_copy_and_parse(
    name: str, advices: dict[str, Advice], tmp_path: Path
) -> None:
    copy = tmp_path / name
    shutil.copytree(target_of(name), copy)
    for patch in advices[name].patches:
        new = apply_patch(copy, patch.diff)
        assert patch.path in new
        for path, content in new.items():
            if path.endswith(".py"):
                ast.parse(content)
            target = copy / path
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(content, encoding="utf-8", newline="")


@pytest.mark.parametrize("name", REPOS)
def test_target_is_not_written(name: str, advices: dict[str, Advice]) -> None:
    assert not (target_of(name) / "supervisor_onboard.py").exists()
    assert not (target_of(name) / "supervisor_onboarding").exists()


def test_fastapi_request_model_route_is_not_decorated(advices: dict[str, Advice]) -> None:
    advice = advices["fastapi_toolserver_remit"]
    assert "tool_gate" not in [p.kind for p in advice.patches]
    site = advice.report.needed.gate_sites[0]
    assert site.mode == "manual" and "gated_send_remittance" in site.note


def test_rename_to_amount_minor_item(advices: dict[str, Advice]) -> None:
    items = advices["injection_bill_pay"].report.needed.manual
    assert any("amount_minor: int" in m.note for m in items)
    assert not any("amount_minor: int" in m.note for m in advices["payments"].report.needed.manual)


def test_tool_gate_goes_below_framework_decorator(advices: dict[str, Advice]) -> None:
    diff = next(p.diff for p in advices["injection_bill_pay"].patches if p.kind == "tool_gate")
    lines = diff.splitlines()
    i = next(k for k, line in enumerate(lines) if line.startswith("+@supervised_tool"))
    assert lines[i - 1] == " @tool" and lines[i + 1].startswith(" def pay_bill")
    assert (
        "+from supervisor.gateway.sdk import supervised_tool  # supervisor-onboard: hook" in lines
    )


def test_mcp_repos_get_a_proxy_patch(advices: dict[str, Advice]) -> None:
    a = advices["fastmcp_account_tools"]
    assert a.report.found.mcp_server and a.report.needed.mcp_proxy
    assert a.report.needed.mcp_proxy.config_path == "mcp.json"
    b = advices["holdout_mcp_lowlevel_cards"]
    assert b.report.needed.mcp_proxy is not None
    assert b.report.needed.mcp_proxy.config_path == "supervisor_onboarding/mcp_proxy.json"
    cmd = b.report.needed.mcp_proxy.command
    assert cmd[:3] == ["python", "-m", "supervisor.gateway.mcp_proxy"] and "--" in cmd


def test_builder_codemod_on_demo_agents(advices: dict[str, Advice]) -> None:
    for name in ("payments", "customer_service", "credit_prequal"):
        assert "builder_hook" in [p.kind for p in advices[name].patches]
        sites = advices[name].report.needed.gate_sites
        assert {s.mode for s in sites} == {"already_gated"}
        assert all(s.note.startswith("central dispatch gate at agent.py:") for s in sites)
        gate = next(a for a in advices[name].report.readiness.areas if a.id == "gate_coverage")
        assert gate.points == 30 and "central dispatch gate at agent.py:" in gate.reason


def test_no_corpus_repo_has_a_central_gate(advices: dict[str, Advice]) -> None:
    for name in REPOS:
        for t in advices[name].report.found.tools:
            assert not t.gated, (name, t.name)
        gate = next(a for a in advices[name].report.readiness.areas if a.id == "gate_coverage")
        assert "central dispatch" not in gate.reason


def test_writing_read_only_tool_is_gated_and_flagged(advices: dict[str, Advice]) -> None:
    a = advices["langchain_card_support"]
    site = next(s for s in a.report.needed.gate_sites if s.tool == "khoa_the_tam_thoi")
    assert site.risk_class == "read_only" and site.mode == "decorator"
    assert '"khoa_the_tam_thoi", "read_only"' in site.decorator
    assert "tool_gate" in [p.kind for p in a.patches]
    item = next(m for m in a.report.needed.manual if "confirm the risk class" in m.what)
    assert "writes found (bank_api write) but classed read_only" in item.note
    assert "fails open when the gateway is down" in item.note
    gate = next(x for x in a.report.readiness.areas if x.id == "gate_coverage")
    assert gate.inputs["gated_tools"] == 1 and gate.points == 0


def test_mcp_patches_are_alternatives(advices: dict[str, Advice]) -> None:
    a = advices["fastmcp_account_tools"]
    for p in a.report.patches:
        if p.kind in ("tool_gate", "mcp_proxy"):
            assert "either the proxy (pattern C) or the decorators (pattern A), not both" in (
                p.description
            )
    assert a.report.needed.mcp_proxy is not None
    assert "not both" in a.report.needed.mcp_proxy.note

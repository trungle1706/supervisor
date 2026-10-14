"""Discover finds each mock agent's tools and prompts with correct file:line evidence."""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

from supervisor.adapters.repo import LocalGitRepoReader
from supervisor.adapters.workspace import FixtureWorkspaceReader
from supervisor.onboard.discover import Discovery, discover
from supervisor.onboard.scrub import Scrubber
from supervisor_agents.common.manifest import load_manifest
from tests.onboard.conftest import AGENT_IDS, AGENTS_DIR


def _line(agent: str, file: str, line: int) -> str:
    return (AGENTS_DIR / agent / file).read_text(encoding="utf-8").splitlines()[line - 1]


@pytest.mark.parametrize("agent", AGENT_IDS)
def test_tools_found_with_file_and_line(agent: str, discoveries: dict[str, Discovery]) -> None:
    inv = discoveries[agent].inventory
    manifest = load_manifest(agent)
    assert inv.agent_id == agent
    assert [t.name for t in inv.tools] == sorted(manifest.tool_names)
    for t in inv.tools:
        spec = manifest.tool(t.name)
        assert spec is not None
        assert t.risk_class == spec.risk_class
        assert t.risk_source == "manifest"
        # definition: the nested tool function in agent.py
        assert t.definition is not None and t.definition.file == "agent.py"
        assert f"def {t.name}(" in _line(agent, "agent.py", t.definition.line)
        # manifest entry
        assert t.manifest_entry is not None and t.manifest_entry.file == "manifest.yaml"
        assert f"name: {t.name}" in _line(agent, "manifest.yaml", t.manifest_entry.line)


@pytest.mark.parametrize("agent", AGENT_IDS)
def test_prompts_found_with_file_and_line(agent: str, discoveries: dict[str, Discovery]) -> None:
    inv = discoveries[agent].inventory
    system = [p for p in inv.prompts if p.kind == "system"]
    assert system, "manifest description (the system prompt source) not found"
    ev = system[0].evidence
    assert ev.file == "manifest.yaml"
    assert ev.quote and ev.quote in _line(agent, "manifest.yaml", ev.line)
    assert load_manifest(agent).description.startswith(system[0].excerpt[:30])
    tasks = [p for p in inv.prompts if p.kind == "task"]
    assert tasks, "scripted task prompts not found"
    for p in tasks:
        assert p.evidence.file == "tasks.py"
        assert "prompt=" in _line(agent, "tasks.py", p.evidence.line)


@pytest.mark.parametrize("agent", AGENT_IDS)
def test_all_evidence_points_at_real_lines(agent: str, discoveries: dict[str, Discovery]) -> None:
    d = discoveries[agent]
    inv = d.inventory
    evs = [e for t in inv.tools for e in (t.definition, t.manifest_entry) if e]
    evs += [p.evidence for p in inv.prompts] + [lim.evidence for lim in inv.limits]
    evs += [n.evidence for n in inv.notes] + list(inv.pii_fields.values())
    evs += [e.evidence for e in inv.entrypoints if e.evidence]
    assert evs
    for e in evs:
        assert d.index.verify(e), e.ref()
        assert e.quote in _line(agent, e.file, e.line)


def test_payments_specifics(discoveries: dict[str, Discovery]) -> None:
    inv = discoveries["payments"].inventory
    ext = inv.tool("ext_transfer_api")
    assert ext is not None and ext.approved is False
    assert ext.approval_evidence is not None
    assert "not approved" in ext.approval_evidence.quote
    tr = inv.tool("transfer")
    assert tr is not None
    assert (tr.amount_arg, tr.destination_arg, tr.key_args) == (
        "amount_minor",
        "payee_id",
        ["from_account_id"],
    )
    assert "transfers" in tr.mutates
    limits = {lim.key: (lim.tool, lim.period, lim.value) for lim in inv.limits}
    assert limits == {
        "transfer_max_minor": ("transfer", "per_call", 100_000_000),
        "daily_transfer_max_minor": ("transfer", "daily", 300_000_000),
    }
    assert not any(lim.enforced_in_code for lim in inv.limits)
    assert [e.name for e in inv.entrypoints] == ["build_agent"]
    assert inv.model_endpoints[0].name == "qwen3:4b"
    assert {"otel_spans", "destination_arg", "declared_limit"} <= set(inv.features)


def test_credit_and_service_specifics(discoveries: dict[str, Discovery]) -> None:
    credit = discoveries["credit_prequal"].inventory
    fetch = credit.tool("fetch_application")
    assert fetch is not None and "documents_complete" in fetch.returns_fields
    assert credit.constants["DECISIONS"] == ["approve", "refer", "decline"]
    assert {"record_fact", "prior_read", "decision_tool"} <= set(credit.features)
    assert any(n.kind == "human_step" for n in credit.notes)
    svc = discoveries["customer_service"].inventory
    waive = [lim for lim in svc.limits if lim.key == "waive_fee_max_minor"]
    assert waive and waive[0].enforced_in_code  # the tool reads the manifest limit
    assert "destination_arg" not in svc.features


def test_secrets_are_scrubbed_and_lines_kept(tmp_path: Path) -> None:
    repo = tmp_path / "agent"
    shutil.copytree(AGENTS_DIR / "payments", repo, ignore=shutil.ignore_patterns("__pycache__"))
    pem = "-----BEGIN RSA PRI" + "VATE KEY-----\nAAAA\nBBBB\n-----END RSA PRI" + "VATE KEY-----"
    token = "da" + "pi" + "0123456789abcdef" * 2
    (repo / "settings.py").write_text(
        f'"""Config."""\nKEY = """{pem}"""\nTOKEN = "{token}"\n\n\ndef build_agent(gate=None):\n'
        "    return gate\n",
        encoding="utf-8",
    )
    scrub = Scrubber()
    d = discover(LocalGitRepoReader(repo), scrubber=scrub)
    assert scrub.totals == {"pem_private_key": 1, "databricks_token": 1}
    rows = d.index.lines["settings.py"]
    assert token not in "\n".join(rows) and "AAAA" not in "\n".join(rows)
    # line numbers survive the multi-line PEM redaction: def build_agent is on line 9
    eps = [e for e in d.inventory.entrypoints if e.evidence and e.evidence.file == "settings.py"]
    assert eps and eps[0].evidence.line == 9
    assert d.inventory.scrub["secrets_redacted"] == 2
    assert d.inventory.secret_refs
    assert all("[REDACTED:" in e.quote for e in d.inventory.secret_refs)


def test_workspace_fixture_adds_endpoints_tables_and_traces(tmp_path: Path) -> None:
    fixture = {
        "serving_endpoints": [{"name": "payments-llm", "family": "qwen"}],
        "apps": [{"name": "payments-app"}],
        "lineage": [
            {"agent": "payments", "table": "bank.core.transfers", "direction": "write"},
            {"agent": "other", "table": "bank.core.x", "direction": "read"},
        ],
        "traces": [{"agent": "payments", "source": "mlflow", "count": 120}],
    }
    p = tmp_path / "ws.json"
    p.write_text(json.dumps(fixture), encoding="utf-8")
    d = discover(
        LocalGitRepoReader(AGENTS_DIR / "payments"),
        workspace=FixtureWorkspaceReader.from_file(p),
    )
    inv = d.inventory
    assert ("bank.core.transfers", "write") in [(t.name, t.direction) for t in inv.tables]
    assert "bank.core.x" not in [t.name for t in inv.tables]
    assert any(e.source == "workspace" and e.name == "payments-llm" for e in inv.model_endpoints)
    assert any(t.detail == "120 existing traces" for t in inv.traces)
    assert inv.apps == ["payments-app"]


def test_code_tables_and_mcp(tmp_path: Path) -> None:
    repo = tmp_path / "a"
    repo.mkdir()
    (repo / "agent.py").write_text(
        "import mcp\n"
        'Q = "SELECT * FROM bank.core.accounts a JOIN bank.core.cards c ON a.id = c.id"\n'
        'W = "INSERT INTO bank.audit.log VALUES (1)"\n'
        "def run(spark):\n"
        '    spark.table("bank.core.loans")\n'
        '    df.write.saveAsTable("bank.out.scores")\n',
        encoding="utf-8",
    )
    inv = discover(LocalGitRepoReader(repo)).inventory
    tables = {(t.name, t.direction) for t in inv.tables}
    assert {
        ("bank.core.accounts", "read"),
        ("bank.core.cards", "read"),
        ("bank.audit.log", "write"),
        ("bank.core.loans", "read"),
        ("bank.out.scores", "write"),
    } <= tables
    assert inv.mcp_servers and inv.mcp_servers[0].name == "mcp"
    assert inv.agent_id == "a"

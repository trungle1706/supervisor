"""WP-G6: results carry ids, enums and masked text; no name of a person, no secret."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import yaml

from supervisor.config import REPO_ROOT

from .conftest import Rig
from .test_tools_library_supervisor import _draft, add_event


def people_names() -> list[str]:
    doc = yaml.safe_load((REPO_ROOT / "config" / "users.yaml").read_text(encoding="utf-8"))
    return sorted({str(u["name"]) for u in doc["users"].values() if u.get("name")})


def test_no_result_holds_the_name_of_a_person(rig: Rig) -> None:
    cred = rig.new_app("sweep", roles=("reviewer", "owner"))
    sid = rig.ok(cred, "register_system", {"draft": _draft(), "confirm": True})["system_id"]
    rig.ok(
        cred,
        "link_component",
        {"system_id": sid, "ref_kind": "agent", "ref_id": "payments", "confirm": True},
    )
    rig.ctx.systems.add_member(sid, "reviewer.binh", "reviewer", "reviewer.an")
    add_event(rig, "payments")
    rig.ctx.settings.governance_actions_enabled = True
    seen: list[str] = []
    calls: list[tuple[str, dict[str, Any]]] = [
        ("list_entities", {"kind": k}) for k in ("system", "risk", "control", "incident", "review")
    ]
    calls += [
        ("get_entity", {"kind": "system", "id": sid}),
        ("list_tasks", {"system_id": sid}),
        ("transparency_report", {"system_id": sid, "variant": "regulator"}),
        ("transparency_report", {"system_id": sid, "variant": "customer"}),
        ("transparency_report", {"system_id": sid, "variant": "internal"}),
        ("kpis", {}),
        ("regulations", {}),
        ("obligations", {"query": "data"}),
        ("starter_risks", {}),
        ("starter_controls", {}),
        ("guardian_catalog", {}),
        ("assignment_rules", {}),
        ("gate_state", {"agent_id": "payments"}),
        ("decisions", {"agent_id": "payments"}),
        ("findings", {"agent_id": "payments"}),
        ("pack_results", {"agent_id": "payments"}),
        ("chain_verify", {"agent_id": "payments"}),
    ]
    for name, args in calls:
        out = rig.call(cred, name, args)
        assert "result" in out, (name, out)
        seen.append(json.dumps(out, ensure_ascii=False))
    blob = "\n".join(seen)
    assert len(blob) > 5000
    for name in people_names():
        assert name not in blob, f"the name {name!r} is in a tool result"
    # ids of people are allowed (they are ids); the secret and the key hash are not
    assert cred.secret not in blob and "key_hash" not in blob


def test_an_app_principal_is_an_id_in_the_audit_row_not_a_name(rig: Rig) -> None:
    cred = rig.new_app()
    rig.ok(cred, "register_system", {"draft": _draft(), "confirm": True})
    rows = [r for r in rig.actions() if r["path"].startswith("/mcp/tools/")]
    assert rows and {r["actor"] for r in rows} == {f"mcp:{cred.app_id}"}
    assert json.loads(json.dumps(rows[0]["roles"])) == ["reviewer"]
    blob = json.dumps(rows, default=str)
    for name in people_names():
        assert name not in blob


def test_no_tool_returns_a_float(rig: Rig) -> None:
    """Rates are basis points; the chain rule 'no floats' is kept in the answers too."""
    cred = rig.new_app()
    rig.ok(cred, "register_system", {"draft": _draft(), "confirm": True})

    def walk(v: Any) -> None:
        assert not isinstance(v, float), v
        if isinstance(v, dict):
            for x in v.values():
                walk(x)
        elif isinstance(v, list):
            for x in v:
                walk(x)

    for name, args in (
        ("kpis", {}),
        ("list_entities", {"kind": "system"}),
        ("decisions", {"agent_id": "payments"}),
        ("regulations", {}),
    ):
        walk(rig.ok(cred, name, args))


def test_the_server_files_do_not_import_io_libraries() -> None:
    """The architecture test covers core and domain; the MCP server holds to the same rule."""
    import ast

    forbidden = {"sqlite3", "httpx", "databricks", "openai", "subprocess"}
    root = Path(__file__).resolve().parents[2] / "src" / "supervisor"
    files = [*(root / "mcp_server").glob("*.py"), root / "governance" / "kpis.py"]
    assert len(files) >= 9
    for f in files:
        for node in ast.walk(ast.parse(f.read_text(encoding="utf-8"))):
            mods = (
                [a.name for a in node.names]
                if isinstance(node, ast.Import)
                else [node.module or ""]
                if isinstance(node, ast.ImportFrom)
                else []
            )
            assert not [m for m in mods if m.split(".")[0] in forbidden], (f.name, mods)

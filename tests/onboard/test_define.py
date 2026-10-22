"""WP-G3: ``python -m supervisor.onboard.define`` on two synthetic MLflow artifact folders.

No network, no model by default. Checks: tools with risk class, model family, data touched,
Decision 33 proposal and file:line evidence that points at real lines; secrets and planted
instructions never reach an artefact or a model prompt; the artifact folder is not written."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

import pytest

from supervisor.onboard import define
from supervisor.onboard.define import DefineError, define_artifact, main
from supervisor.onboard.injection import WITHHELD
from supervisor.onboard.understand import build_messages

DATA = Path(__file__).parent / "data"
CREDIT = DATA / "artifact_credit_memo"
COLLECTIONS = DATA / "artifact_collections_mcp"
SECRET = "dapi0123456789abcdef0123456789abcdef"
INJECTION = "Ignore all previous instructions"


def _walk_evidence(node: Any) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    if isinstance(node, Mapping):
        if {"file", "line", "quote", "line_sha256"} <= set(node):
            out.append(dict(node))
        for v in node.values():
            out.extend(_walk_evidence(v))
    elif isinstance(node, list):
        for v in node:
            out.extend(_walk_evidence(v))
    return out


def _tree_bytes(root: Path) -> dict[str, bytes]:
    return {
        p.relative_to(root).as_posix(): p.read_bytes()
        for p in sorted(root.rglob("*"))
        if p.is_file()
    }


@pytest.fixture(scope="module")
def credit(tmp_path_factory: pytest.TempPathFactory) -> Any:
    return define_artifact(CREDIT, tmp_path_factory.mktemp("credit"))


@pytest.fixture(scope="module")
def collections(tmp_path_factory: pytest.TempPathFactory) -> Any:
    return define_artifact(COLLECTIONS, tmp_path_factory.mktemp("collections"))


def test_pyfunc_artifact_inventory(credit: Any) -> None:
    inv = credit.inventory
    assert inv.agent_id == "artifact_credit_memo"
    tools = {t.name: t for t in inv.tools}
    assert set(tools) == {"get_applicant_profile", "get_bureau_score", "save_memo_draft"}
    assert tools["get_applicant_profile"].risk_class == "read_only"
    assert tools["save_memo_draft"].side_effects == ["db write"]
    assert tools["get_applicant_profile"].manifest_entry.file == "tools.json"  # type: ignore[union-attr]
    assert inv.model_family == "meta" and inv.model_id == "databricks-meta-llama-3-3-70b-instruct"
    assert inv.framework == "databricks_agents"
    assert {(t.name, t.direction) for t in inv.tables} == {
        ("main.lending.loan_applications", "read"),
        ("main.lending.bureau_scores", "read"),
        ("main.lending.memo_drafts", "write"),
    }
    assert "customer_id" in inv.pii_fields
    assert [(p.kind, p.evidence.file) for p in inv.prompts] == [
        ("system", "prompts/system_prompt.txt")
    ]
    assert credit.profile.decision33.classification == "not_high_risk"
    assert credit.profile.llm.used is False


def test_langgraph_artifact_with_mcp_and_money_tool(collections: Any) -> None:
    inv, prof = collections.inventory, collections.profile
    tools = {t.name: t.risk_class for t in inv.tools}
    assert tools["waive_late_fee"] == "money" and tools["lookup_account"] == "read_only"
    assert inv.model_family == "anthropic"
    assert inv.framework == "langgraph"
    assert [m.name for m in inv.mcp_servers] == ["core-banking-mcp"]
    assert inv.human_approval_refs  # request_officer_approval() in the code
    assert prof.proposed_risk_tier in ("high", "critical")
    assert {c for c in prof.tool_risk_classes.values()} >= {"money", "read_only"}
    assert prof.decision33.classification in ("high_risk", "not_high_risk")
    assert prof.decision33.wording_caveat  # a proposal: counsel confirms


def test_every_evidence_pointer_is_a_real_line(credit: Any, collections: Any) -> None:
    for res, root in ((credit, CREDIT), (collections, COLLECTIONS)):
        blobs = [res.inventory.model_dump(mode="json"), res.profile.model_dump(mode="json")]
        evidence = [e for b in blobs for e in _walk_evidence(b)]
        assert len(evidence) > 10
        for ev in evidence:
            rows = (root / ev["file"]).read_text(encoding="utf-8").splitlines()
            assert 1 <= ev["line"] <= len(rows), ev
            if "[REDACTED" in ev["quote"] or ev["quote"] == WITHHELD:
                continue
            assert ev["quote"].strip() in rows[ev["line"] - 1], ev
            assert (
                hashlib.sha256(rows[ev["line"] - 1].strip().encode()).hexdigest()
                == ev["line_sha256"]
            )


def test_mlmodel_and_requirements_facts_have_evidence(credit: Any, collections: Any) -> None:
    a = credit.artifact
    assert a["mlmodel"]["task"] == {"value": "agent/v1/chat", "evidence": "MLmodel:12"}
    assert a["mlmodel"]["flavors"][0]["name"] == "python_function"
    assert {r["package"] for r in a["requirements"]} == {"mlflow", "databricks-agents", "openai"}
    names = {f["name"] for f in collections.artifact["mlmodel"]["flavors"]}
    assert names == {"langchain", "python_function"}
    # no run id, model uuid or creation time is copied
    assert "uuid" not in json.dumps(a) and "run_id" not in json.dumps(a)


def test_secret_never_reaches_an_artefact(credit: Any) -> None:
    assert (CREDIT / "config.yaml").read_text(encoding="utf-8").count(SECRET) == 1  # it is there
    for p in credit.artefacts.values():
        assert SECRET not in p.read_text(encoding="utf-8")
    assert credit.inventory.scrub["secrets_redacted"] == 1
    assert credit.inventory.secret_refs  # where it was found, without the value


def test_text_for_a_model_is_scrubbed_and_planted_instruction_is_flagged(
    credit: Any, collections: Any
) -> None:
    from supervisor.adapters.repo import LocalGitRepoReader
    from supervisor.onboard.discover import ARTIFACT_MANIFEST_NAMES, discover

    for root in (CREDIT, COLLECTIONS):
        disc = discover(LocalGitRepoReader(root), manifest_names=ARTIFACT_MANIFEST_NAMES)
        messages = build_messages(disc.inventory, disc.index)
        text = "\n".join(m["content"] for m in messages)
        assert SECRET not in text


class _SpyChat:
    family = "other"
    model_id = "spy-model"
    is_mock = False

    def __init__(self) -> None:
        self.seen: list[str] = []

    def complete_json(
        self,
        messages: Sequence[Mapping[str, str]],
        json_schema: Mapping[str, Any],
        timeout_s: float,
    ) -> Mapping[str, Any]:
        self.seen.extend(m["content"] for m in messages)
        return {"claims": []}


def test_model_step_sees_only_scrubbed_text(tmp_path: Path) -> None:
    chat = _SpyChat()
    res = define_artifact(CREDIT, tmp_path / "o", chat=chat)  # type: ignore[arg-type]
    assert chat.seen and res.profile.llm.used is True and res.profile.llm.is_mock is False
    assert all(SECRET not in s for s in chat.seen)


def test_planted_instruction_does_not_change_the_result_or_reach_an_artefact(
    collections: Any,
) -> None:
    assert collections.profile.proposed_risk_tier in ("high", "critical")
    for p in collections.artefacts.values():
        assert INJECTION.lower() not in p.read_text(encoding="utf-8").lower()
    assert collections.inventory.injection_refs  # found and flagged, text withheld


def test_artifact_folder_is_not_written(tmp_path: Path) -> None:
    before = _tree_bytes(CREDIT)
    define_artifact(CREDIT, tmp_path / "o")
    assert _tree_bytes(CREDIT) == before


def test_out_inside_the_artifact_is_refused(tmp_path: Path) -> None:
    src = tmp_path / "art"
    src.mkdir()
    (src / "agent.py").write_text("x = 1\n", encoding="utf-8")
    with pytest.raises(DefineError, match="outside the artifact"):
        define_artifact(src, src / "out")
    with pytest.raises(DefineError, match="does not exist"):
        define_artifact(tmp_path / "missing", tmp_path / "o")


def test_plain_folder_without_mlmodel_is_read_with_a_skip_line(tmp_path: Path) -> None:
    src = tmp_path / "plain_agent"
    src.mkdir()
    (src / "agent.py").write_text('MODEL = "qwen3:4b"\n', encoding="utf-8")
    res = define_artifact(src, tmp_path / "o")
    assert any(line.startswith("[SKIP] no MLmodel") for line in res.lines)
    assert res.artifact["mlmodel"] == {}


def test_cli_prints_ascii_ok_lines_and_writes_files(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    out = tmp_path / "out"
    assert main(["--artifact", str(COLLECTIONS), "--out", str(out), "--mock-llm"]) == 0
    text = capsys.readouterr().out
    assert text.isascii()
    assert "[OK] discover:" in text and "[OK] understand:" in text
    for name in ("inventory.json", "profile.json", "profile.md", "artifact.json"):
        assert (out / name).is_file()
    assert json.loads((out / "profile.json").read_text(encoding="utf-8"))["llm"]["is_mock"] is True


def test_cli_fail_line_for_a_missing_folder(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert main(["--artifact", str(tmp_path / "nope"), "--out", str(tmp_path / "o")]) == 1
    out = capsys.readouterr().out
    assert out.startswith("[FAIL] define stopped") and out.isascii()


def test_module_has_no_forbidden_imports() -> None:
    src = Path(define.__file__).read_text(encoding="utf-8")
    for bad in (
        "import databricks",
        "import httpx",
        "import openai",
        "import sqlite3",
        "subprocess",
    ):
        assert bad not in src


# ------------------------------------------------------------------ autonomy level proposal
BATCH = DATA / "artifact_batch_summariser"


def _autonomy(tmp_path: Path, src: Path) -> dict[str, Any]:
    res = define_artifact(src, tmp_path / "o")
    on_disk = json.loads((tmp_path / "o" / "profile.json").read_text(encoding="utf-8"))
    assert on_disk["autonomy_level_proposal"] == res.autonomy
    return res.autonomy


def _check_evidence(a: dict[str, Any], root: Path) -> None:
    assert a["evidence"] and a["why"] and a["is_proposal"] is True
    for ev in a["evidence"]:
        rows = (root / ev["file"]).read_text(encoding="utf-8").splitlines()
        assert 1 <= ev["line"] <= len(rows)


def test_batch_job_with_no_tool_is_l2(tmp_path: Path) -> None:
    a = _autonomy(tmp_path, BATCH)
    assert a["level"] == "l2_workflow_step"
    _check_evidence(a, BATCH)


def test_tools_without_approval_are_l4(tmp_path: Path) -> None:
    a = _autonomy(tmp_path, CREDIT)
    assert a["level"] == "l4_autonomous_bounded" and "no approval step" in a["why"]
    _check_evidence(a, CREDIT)


def test_tools_each_behind_an_approval_step_are_l3(tmp_path: Path) -> None:
    a = _autonomy(tmp_path, COLLECTIONS)
    assert a["level"] == "l3_tool_using_supervised"
    _check_evidence(a, COLLECTIONS)


def _plain(tmp_path: Path, code: str) -> dict[str, Any]:
    src = tmp_path / "art"
    src.mkdir()
    (src / "agent.py").write_text(code, encoding="utf-8")
    return define_artifact(src, tmp_path / "o").autonomy


def test_no_model_is_l0_chat_endpoint_is_l1_spawning_is_l5(tmp_path: Path) -> None:
    chat = (
        "from fastapi import FastAPI\nfrom openai import OpenAI\napp = FastAPI()\n"
        '@app.post("/chat")\ndef chat(q: str):\n'
        '    return OpenAI().chat.completions.create(model="gpt-4o", messages=[])\n'
    )
    cases = {
        "a": ("def f(x):\n    return x + 1\n", "l0_rule_based"),
        "b": (chat, "l1_assistive"),
        "c": (chat + "def go():\n    spawn_agent('helper')\n", "l5_self_directed"),
    }
    for name, (code, level) in cases.items():
        (tmp_path / name).mkdir()
        assert _plain(tmp_path / name, code)["level"] == level, name

"""WP-P1: `demo seed-systems` registers AI systems from candidate manifests (fixtures only)."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
import yaml

from supervisor.config import Settings
from supervisor.demo import runbook
from supervisor.demo.seed_systems import (
    MANIFEST_NAME,
    ManifestError,
    parse_manifest,
    seed_systems,
)
from supervisor.demo.session import build_session, demo_settings


def manifest(name: str, agent_id: str, risk_class: str = "read_only", **system: Any) -> dict:
    sys_part: dict[str, Any] = {
        "name": name,
        "owner_user": "owner.credit",
        "owner_team": "SME Credit Underwriting (synthetic)",
        "purpose": "Synthetic purpose for a fixture.",
        "system_type": "assistant",
        "org_role": "deployer",
        "user_segment": "internal",
        "personal_data": "none",
        "money_movement": False,
        "credit_decision": False,
        "human_control": "post_review",
        "business_impact": "medium",
        "autonomy_level": "l1_assistive",
    }
    sys_part.update(system)
    return {
        "manifest_version": 1,
        "system": sys_part,
        "agent": {
            "agent_id": agent_id,
            "name": name,
            "model_family": "qwen",
            "plug_point": "fastapi_middleware",
            "tools": [
                {"name": "t1", "risk_class": "read_only", "description": "x"},
                {"name": "t2", "risk_class": risk_class, "description": "y"},
            ],
            "policy_fragment": f"policies/{agent_id}.yaml",
            "artifact_dir": "artifact",
        },
    }


def put(root: Path, folder: str, doc: Any) -> None:
    d = root / folder
    d.mkdir(parents=True, exist_ok=True)
    text = doc if isinstance(doc, str) else yaml.safe_dump(doc)
    (d / MANIFEST_NAME).write_text(text, encoding="utf-8")


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    return demo_settings(
        tmp_path / "demo", llm_base_url="", governance_enabled=True, classifier_ai_prefill=False
    )


@pytest.fixture
def cands(tmp_path: Path) -> Path:
    root = tmp_path / "candidates"
    put(root, "kb", manifest("Fixture knowledge bot", "fx_kb"))
    put(
        root,
        "pay",
        manifest("Fixture payments bot", "fx_pay", risk_class="money", money_movement=True),
    )
    return root


def test_parse_manifest_risk_tier_is_highest_tool_class(cands: Path) -> None:
    low = parse_manifest((cands / "kb" / MANIFEST_NAME).read_text(), cands / "kb")
    high = parse_manifest((cands / "pay" / MANIFEST_NAME).read_text(), cands / "pay")
    assert low.risk_tier == "low"
    assert high.risk_tier == "high"
    assert high.system["money_movement"] is True


@pytest.mark.parametrize(
    ("mutate", "needle"),
    [
        (lambda d: d.update(manifest_version=2), "manifest_version"),
        (lambda d: d["system"].pop("owner_user"), "owner_user"),
        (lambda d: d["agent"].update(tools=[]), "tools"),
        (lambda d: d["agent"]["tools"][0].update(risk_class="nuclear"), "risk_class"),
        (lambda d: d["agent"].update(plug_point="telepathy"), "plug_point"),
        (lambda d: d["agent"].update(agent_id="inventory"), "reserved"),
        (lambda d: d["system"].update(money_movement="yes please"), "money_movement"),
    ],
)
def test_parse_manifest_rejects(mutate: Any, needle: str) -> None:
    doc = manifest("X", "fx_x")
    mutate(doc)
    with pytest.raises(ManifestError, match=needle):
        parse_manifest(yaml.safe_dump(doc), Path("x"))


def test_parse_manifest_rejects_bad_yaml() -> None:
    with pytest.raises(ManifestError):
        parse_manifest("a: [unclosed", Path("x"))
    with pytest.raises(ManifestError):
        parse_manifest("- just\n- a list\n", Path("x"))


def test_seed_registers_links_and_drafts(settings: Settings, cands: Path) -> None:
    lines: list[str] = []
    rep = seed_systems(settings, cands, echo=lines.append)
    assert rep.ok and rep.created == 2 and len(rep.systems) == 2
    assert all(sid.startswith("sys_") for sid in rep.systems.values())
    session = build_session(settings)
    try:
        agent = session.state.get("agent", {"agent_id": "fx_pay"})
        assert agent["risk_tier"] == "high"
        assert agent["host_type"] == "app"
        assert agent["plug_point"] == "fastapi_middleware"
        assert agent["model_family"] == "qwen"
        assert agent["owner_team"] == "SME Credit Underwriting (synthetic)"
        sid = rep.systems["Fixture payments bot"]
        view = session.console.systems.get(sid)
        assert view["money_movement"]
        assert [c["ref_id"] for c in view["components"]] == ["fx_pay"]
        assert view["autonomy_level"] == "l1_assistive"
        cls = session.console.classification.get(sid)
        assert cls["draft"] is not None and cls["applied"] is None
        assert view["decision33_class"] == "unclassified"  # drafted, never applied
    finally:
        session.close()
    assert any(line.startswith("[OK] seed-systems") for line in lines)


def test_seed_is_idempotent(settings: Settings, cands: Path) -> None:
    first = seed_systems(settings, cands, echo=lambda _l: None)
    second = seed_systems(settings, cands, echo=lambda _l: None)
    assert second.ok and second.created == 0
    assert second.systems == first.systems
    session = build_session(settings)
    try:
        assert len(session.state.query("ai_system")) == 2
        assert len(session.state.query("system_component")) == 2
        assert len(session.state.query("classification")) == 2
    finally:
        session.close()


def test_missing_and_invalid_manifests_are_skipped(settings: Settings, cands: Path) -> None:
    (cands / "empty").mkdir()
    put(cands, "broken", "manifest_version: 1\nsystem: 3\n")
    put(cands, "badenum", manifest("Fixture bad enum", "fx_bad", system_type="spaceship"))
    (cands / ".hidden").mkdir()
    lines: list[str] = []
    rep = seed_systems(settings, cands, echo=lines.append)
    assert rep.ok
    assert len(rep.systems) == 2
    skips = [ln for ln in lines if ln.startswith("[SKIP]")]
    assert len(skips) == 3
    assert any("empty" in s and "not found" in s for s in skips)
    assert any("broken" in s for s in skips)
    assert any("badenum" in s for s in skips)
    assert not any(".hidden" in ln for ln in lines)


def test_no_candidates_folder_is_a_skip(settings: Settings, tmp_path: Path) -> None:
    lines: list[str] = []
    rep = seed_systems(settings, tmp_path / "does-not-exist", echo=lines.append)
    assert rep.ok and rep.systems == {}
    assert lines[0].startswith("[SKIP]")


def test_refuses_a_data_dir_that_is_not_a_demo_dir(tmp_path: Path, cands: Path) -> None:
    other = tmp_path / "real-data"
    other.mkdir()
    (other / "precious.txt").write_text("x", encoding="utf-8")
    s = demo_settings(other, llm_base_url="", governance_enabled=True)
    rep = seed_systems(s, cands, echo=lambda _l: None)
    assert not rep.ok
    assert [p.name for p in other.iterdir()] == ["precious.txt"]


def test_output_is_ascii_and_cli_step_runs(
    tmp_path: Path, cands: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    put(cands, "vi", manifest("Fixture Việt bot", "fx_vi", purpose="Trợ lý"))
    data = tmp_path / "cli-demo"
    rc = runbook.main(["seed-systems", "--data-dir", str(data), "--candidates-dir", str(cands)])
    out = capsys.readouterr().out
    assert rc == 0
    out.encode("ascii")
    assert "[OK] seed-systems: 3 system(s) present, 3 new" in out

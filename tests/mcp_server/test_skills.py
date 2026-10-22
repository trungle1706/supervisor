"""WP-G6 skills: Markdown files under docs/skills/ that name real tools, the scopes those tools
need, and the three rules."""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from supervisor.mcp_server.registry import refusal_for
from supervisor.mcp_server.server import build_registry

SKILLS = Path(__file__).resolve().parents[2] / "docs" / "skills"
NAMES = ["vn-system-registration", "d33-prep", "risk-triage", "transparency-report", "gov-report"]
RULE = "The server decides. Confirm before you write. Never classify by yourself."


def test_exactly_the_five_skills_exist() -> None:
    assert sorted(p.stem for p in SKILLS.glob("*.md")) == sorted(NAMES)


@pytest.mark.parametrize("name", NAMES)
def test_a_skill_names_real_tools_and_scopes_and_the_rule(name: str) -> None:
    text = (SKILLS / f"{name}.md").read_text(encoding="utf-8")
    assert text.startswith(f"# Skill: {name}\n")
    assert RULE in text
    tools_line = next(line for line in text.splitlines() if line.startswith("Tools used:"))
    scopes_line = next(line for line in text.splitlines() if line.startswith("Scopes:"))
    used = re.findall(r"`([a-z_]+)`", tools_line)
    reg = build_registry()
    assert used and all(reg.get(t) is not None for t in used), [t for t in used if not reg.get(t)]
    assert not [t for t in used if refusal_for(t)]
    scopes = set(re.findall(r"`([a-z]+\.[a-z]+)`", scopes_line))
    assert {reg.get(t).scope for t in used if reg.get(t)} <= scopes  # type: ignore[union-attr]
    # every backticked word that looks like a tool call in the body is a real tool
    body = text.split("\n## ", 1)[1]
    called = set(re.findall(r"`([a-z]+_[a-z_]+)`", body))
    known_words = {
        "ref_kind",
        "owner_user",
        "owner_team",
        "system_type",
        "org_role",
        "user_segment",
        "personal_data",
        "human_control",
        "business_owner",
        "money_movement",
        "credit_decision",
        "autonomy_level",
        "system_id",
        "agent_id",
        "ai_prefill",
        "decided_by_rule",
        "info_status",
        "implementation_by_system",
        "business_impact",
        "risk_level",
        "planned_change",
        "post_review",
        "pre_approval",
    }
    unknown = {w for w in called if reg.get(w) is None and w not in known_words and "." not in w}
    assert not unknown, unknown


def test_a_write_skill_tells_the_two_step_confirm() -> None:
    for name in ("vn-system-registration", "d33-prep", "risk-triage"):
        text = (SKILLS / f"{name}.md").read_text(encoding="utf-8")
        assert "confirm: true" in text and "without `confirm`" in text.replace(
            "without confirm", "without `confirm`"
        )


def test_a_read_skill_says_it_writes_nothing() -> None:
    for name in ("transparency-report", "gov-report"):
        text = (SKILLS / f"{name}.md").read_text(encoding="utf-8")
        assert "only reads" in text
        used = re.findall(
            r"`([a-z_]+)`", next(x for x in text.splitlines() if x.startswith("Tools used:"))
        )
        assert not [t for t in used if build_registry().get(t).write]  # type: ignore[union-attr]

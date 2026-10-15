"""WP15: the integration advisor as an optional run stage (ONBOARD_ADVISOR_ENABLED, off)."""

from __future__ import annotations

import json
import shutil
from pathlib import Path

from supervisor.adapters.llm.mock import MockChat
from supervisor.config import load_settings
from supervisor.onboard.run import ARTEFACTS, OnboardResult, run_onboarding
from tests.conftest import REPO_ROOT

REPO = "langchain_card_support"
ADVICE = ("integration_report.json", "integration_report.md", "integration_report.html")


def _run(tmp_path: Path, enabled: bool) -> tuple[OnboardResult, Path]:
    target = tmp_path / REPO
    shutil.copytree(REPO_ROOT / "data" / "corpus" / "repos" / REPO, target)
    out = tmp_path / "out"
    settings = load_settings(
        sql_backend="sqlite", data_dir=tmp_path / "data", onboard_advisor_enabled=enabled
    )
    res = run_onboarding(
        target, out, settings=settings, chat=MockChat(model_id="mock-onboarding-v1")
    )
    return res, out


def test_off_keeps_the_artefact_set(tmp_path: Path) -> None:
    assert load_settings(sql_backend="sqlite").onboard_advisor_enabled is False
    res, out = _run(tmp_path, False)
    assert set(res.artefacts) == set(ARTEFACTS)
    names = {p.name for p in out.iterdir() if p.is_file()}
    assert names == set(ARTEFACTS)
    assert not any("advise" in line for line in res.lines)
    handover = json.loads((out / "handover.json").read_text(encoding="utf-8"))
    assert set(handover["artefacts"]) == set(ARTEFACTS) - {"handover.json"}


def test_on_adds_report_and_patches_to_the_handover(tmp_path: Path) -> None:
    res, out = _run(tmp_path, True)
    extra = set(res.artefacts) - set(ARTEFACTS)
    patches = {n for n in extra if n.startswith("integration_patch_") and n.endswith(".patch")}
    assert extra == set(ADVICE) | patches and patches
    for n in sorted(patches):
        assert "/" not in n and (out / n).read_text(encoding="utf-8").startswith("diff --git")
    assert (out / "integration_report.json").is_file()
    report = json.loads((out / "integration_report.json").read_text(encoding="utf-8"))
    assert len(report["patches"]) == len(patches)
    handover = json.loads((out / "handover.json").read_text(encoding="utf-8"))
    assert extra <= set(handover["artefacts"])
    line = next(x for x in res.lines if "] advise:" in x)
    assert line.startswith("[OK] advise: readiness ") and "(never applied)" in line
    assert line.isascii()
    # nothing was applied to the target
    assert not (tmp_path / REPO / "supervisor_onboard.py").exists()

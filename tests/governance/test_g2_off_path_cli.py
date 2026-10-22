"""WP-G2 off path and CLI: flags off = nothing mounted and nothing changes; the CLI runs and
explains in ASCII."""

from __future__ import annotations

from pathlib import Path

import pytest

from supervisor.adapters.factory import Adapters, build_adapters
from supervisor.config import Settings, load_settings
from supervisor.governance import rules as rules_cli
from supervisor.governance.systems import SystemService
from supervisor.jobs import bootstrap_schema
from tests.conftest import REPO_ROOT

from .conftest import Console, ListSink, draft


def test_g2_flags_and_paths_have_safe_defaults() -> None:
    assert Settings.model_fields["classifier_ai_prefill"].default is False
    s = load_settings(sql_backend="sqlite", llm_base_url="")
    assert s.classifier_ai_prefill is False and s.governance_enabled is False
    assert s.assignment_rules_config == REPO_ROOT / "config" / "assignment_rules.yaml"
    assert s.decision33_config == REPO_ROOT / "config" / "decision33.yaml"


def test_no_g2_route_is_mounted_with_the_flag_off() -> None:
    from tests.console.test_rbac_matrix import app_routes

    paths = {p for _, p, _ in app_routes()}
    assert not [p for p in paths if "/assignments" in p or "/classification" in p]
    assert not [p for p in paths if "guardian-floor" in p or "rules/explain" in p]


@pytest.mark.parametrize(
    "url",
    [
        "/v1/systems/sys_x/assignments",
        "/v1/systems/sys_x/guardian-floor",
        "/v1/systems/sys_x/obligations",
        "/v1/systems/sys_x/classification",
    ],
)
def test_g2_urls_do_not_exist_with_the_flag_off(console: Console, url: str) -> None:
    assert console.get(url).status_code == 404


def test_flag_off_service_runs_no_rules_and_writes_nothing(
    adapters: Adapters, sink: ListSink
) -> None:
    assert adapters.settings.governance_enabled is False
    svc = SystemService.from_adapters(adapters, evidence=sink)
    s = svc.register(draft(personal_data="identifiable", user_segment="customer"), "owner.lan")
    svc.update_fields(s["system_id"], {"purpose": "Changed"}, "owner.lan")
    assert adapters.state.query("assignment") == []
    assert adapters.state.query("classification") == []
    assert sink.of("rule_run") == [] and sink.of("classification_change") == []
    assert [t for t, _, _ in sink.records] == ["system_change", "system_change"]


def test_effective_risk_without_a_class_is_what_g0_gave(adapters: Adapters) -> None:
    svc = SystemService.from_adapters(adapters)
    s = svc.register(draft(), "owner.lan")
    eff = svc.effective_risk_level(s["system_id"])
    assert (eff.level, eff.source) == ("unspecified", "manual")
    svc.update_fields(s["system_id"], {"risk_level": "medium"}, "owner.lan")
    assert svc.effective_risk_level(s["system_id"]).level == "medium"


# ---- CLI --------------------------------------------------------------------------------------


def _env(monkeypatch: pytest.MonkeyPatch, tmp_path: Path, on: bool) -> None:
    monkeypatch.setenv("SQL_BACKEND", "sqlite")
    monkeypatch.setenv("LLM_BASE_URL", "")
    monkeypatch.setenv("DATA_DIR", str(tmp_path / "cli"))
    if on:
        monkeypatch.setenv("GOVERNANCE_ENABLED", "1")
    else:
        monkeypatch.delenv("GOVERNANCE_ENABLED", raising=False)


def test_cli_is_a_noop_when_off(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    _env(monkeypatch, tmp_path, False)
    assert rules_cli.main(["run"]) == 0
    assert rules_cli.main(["explain", "--system", "sys_x"]) == 0
    assert capsys.readouterr().out.count("[SKIP]") == 2


def test_cli_check_needs_no_flag(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    _env(monkeypatch, tmp_path, False)
    assert rules_cli.main(["check"]) == 0
    out = capsys.readouterr().out
    assert "[OK] 9 rule(s)" in out and out.isascii()


def test_cli_run_and_explain(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    _env(monkeypatch, tmp_path, True)
    a = build_adapters(load_settings())
    try:
        bootstrap_schema.run(a.settings, a)
        SystemService.from_adapters(a).register(
            draft(personal_data="identifiable", user_segment="customer", money_movement=True),
            "owner.lan",
        )
        sid = a.state.query("ai_system")[0]["system_id"]
        # the service ran the rules at register; wipe nothing, just run again from the CLI
    finally:
        a.close()
    assert rules_cli.main(["run", "--system", sid, "--by", "ops.minh"]) == 0
    out = capsys.readouterr().out
    assert f"[OK] {sid}:" in out and "from 3 rule(s)" in out and out.isascii()
    assert rules_cli.main(["run"]) == 0
    assert "[OK] 1 system(s) evaluated" in capsys.readouterr().out
    assert rules_cli.main(["explain", "--system", sid]) == 0
    text = capsys.readouterr().out
    assert text.isascii() and "rule AR-C53-MONEY: FIRED" in text and "assignments (" in text
    assert "control    CTL-PII-MASK  <- AR-PDPL-CUSTOMER [personal_data, user_segment]" in text
    assert rules_cli.main(["explain", "--system", "sys_missing"]) == 1
    assert "[FAIL]" in capsys.readouterr().out
    assert rules_cli.main(["run", "--by", "bad user"]) == 1
    assert "[FAIL]" in capsys.readouterr().out

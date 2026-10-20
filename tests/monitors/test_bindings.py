"""WP1b-B (D06): per-agent monitor bindings, not_applicable statuses, harness regression."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from supervisor.core.errors import ConfigError
from supervisor.core.monitor_bindings import MonitorBindings
from supervisor.gateway.policy import PolicyDoc
from supervisor.monitors import binding_harness as harness
from supervisor.monitors.bindings import DERIVED, MANIFEST, POLICY, BindingResolver
from supervisor.monitors.status import NO_DATA, NOT_APPLICABLE, OK, read_status, set_status
from tests.conftest import REPO_ROOT


@pytest.fixture(scope="module")
def run(tmp_path_factory: pytest.TempPathFactory) -> dict[str, dict[str, dict]]:
    return harness.run_fixture(tmp_path_factory.mktemp("bindings"))


# ------------------------------------------------------------------------ harness regression


def test_harness_matches_the_golden_statuses(run: dict[str, dict[str, dict]]) -> None:
    golden = json.loads(harness.GOLDEN.read_text(encoding="utf-8"))
    rows, bad = harness.compare(run, golden)
    assert bad == []
    assert len(rows) == 12  # 3 agents x 4 monitors


def test_bound_agent_gets_values_unbound_agent_gets_a_reason(run: dict[str, dict]) -> None:
    for monitor in ("quality", "fairness", "drift", "multiagent"):
        assert run["memo_agent"][monitor]["status"] == OK
        assert run["memo_agent"][monitor]["n"] > 0
    for monitor, entry in run["lookup_agent"].items():
        assert entry["status"] == NOT_APPLICABLE, monitor
        assert entry["reason"], monitor  # never a bare "n/a"


def test_before_wp1b_b_the_monitors_were_silent(tmp_path: Path) -> None:
    """Without the resolver (old behaviour) nothing is written for any of the three agents."""
    assert harness.run_fixture(tmp_path, legacy=True) == {
        "memo_agent": {},
        "helpdesk": {},
        "lookup_agent": {},
    }


def test_harness_cli_exit_code_and_ascii(capsys: pytest.CaptureFixture[str]) -> None:
    assert harness.main([]) == 0
    out = capsys.readouterr().out
    assert out.isascii() and "[FAIL]" not in out and out.count("[OK]") == 12


# ------------------------------------------------------------------------ resolver


def _write(tmp: Path, policy: str, manifest: str = "") -> BindingResolver:
    (tmp / "policies").mkdir(parents=True)
    (tmp / "policies" / "p.yaml").write_text(policy, encoding="utf-8")
    (tmp / "agents" / "a1").mkdir(parents=True)
    (tmp / "agents" / "a1" / "manifest.yaml").write_text(manifest or "id: a1\n", encoding="utf-8")
    return BindingResolver(manifest_roots=[tmp / "agents"], policy_dirs=[tmp / "policies"])


def test_policy_wins_over_manifest_over_derived(tmp_path: Path) -> None:
    manifest = (
        "id: a1\ntools:\n  - {name: say_reply, risk_class: read_only}\n"
        "  - {name: pick, risk_class: credit}\n"
        "monitors:\n  quality: {reply_tools: [from_manifest]}\n"
        "  fairness: {decision_tool: manifest_pick}\n"
    )
    policy = (
        "policy_version: 1\nagents:\n  a1:\n    name: x\n    owner_user: u\n    owner_team: t\n"
        "    monitors:\n      quality: {reply_tools: [from_policy]}\n"
    )
    r = _write(tmp_path, policy, manifest).resolve("a1")
    assert (r.quality.reply_tools, r.quality.source) == (("from_policy",), POLICY)
    assert (r.fairness.decision_tool, r.fairness.source) == ("manifest_pick", MANIFEST)
    only_derived = _write(
        tmp_path / "d",
        "policy_version: 1\n",
        "id: a1\ntools:\n"
        "  - {name: say_reply, risk_class: read_only}\n"
        "  - {name: pick, risk_class: credit}\n"
        "  - {name: pay, risk_class: money}\n",
    ).resolve("a1")
    assert only_derived.quality.reply_tools == ("say_reply",)
    assert only_derived.fairness.decision_tool == "pick"
    assert only_derived.split.tool == "pay"
    assert {only_derived.quality.source, only_derived.fairness.source} == {DERIVED}


def test_policy_overrides_field_by_field_not_whole_section(tmp_path: Path) -> None:
    """Review fix: a policy that sets only approve_values keeps the manifest decision tool."""
    manifest = (
        "id: a1\ntools:\n  - {name: pick, risk_class: credit}\n"
        "monitors:\n  fairness: {decision_tool: manifest_pick, subject_arg: cid}\n"
        "  drift: {window_s: 3600, min_n: 5}\n"
    )
    policy = (
        "policy_version: 1\nagents:\n  a1:\n    name: x\n    owner_user: u\n    owner_team: t\n"
        "    monitors:\n      fairness: {approve_values: [approved]}\n      drift: {min_n: 9}\n"
    )
    r = _write(tmp_path, policy, manifest).resolve("a1")
    assert (r.fairness.decision_tool, r.fairness.source) == ("manifest_pick", MANIFEST)
    assert (r.fairness.subject_arg, r.fairness.approve_values) == ("cid", ("approved",))
    assert r.drift is not None and (r.drift.window_s, r.drift.min_n) == (3600, 9)


def test_ambiguous_tools_are_not_guessed(tmp_path: Path) -> None:
    manifest = (
        "id: a1\ntools:\n  - {name: c1, risk_class: credit}\n  - {name: c2, risk_class: credit}\n"
        "  - {name: m1, risk_class: money}\n  - {name: m2, risk_class: money}\n"
        "  - {name: reply_money, risk_class: money}\n"
    )
    r = _write(tmp_path, "policy_version: 1\n", manifest).resolve("a1")
    assert not r.fairness.bound and "several credit tools" in (r.fairness.gap or "")
    assert not r.split.bound and "several money tools" in (r.split.gap or "")
    assert not r.quality.bound  # a money tool named reply_* is not an output tool


def test_observed_tools_feed_the_derivation(tmp_path: Path) -> None:
    res = _write(tmp_path, "policy_version: 1\ntools: {draft_reply: read_only}\n")
    assert not res.resolve("a1").quality.bound
    assert res.resolve("a1", observed=["draft_reply"]).quality.reply_tools == ("draft_reply",)


def test_bad_binding_is_a_config_error_not_a_silent_off(tmp_path: Path) -> None:
    bad = (
        "policy_version: 1\nagents:\n  a1:\n    name: x\n    owner_user: u\n    owner_team: t\n"
        "    monitors:\n      quality: {reply_tool: [typo]}\n"
    )
    with pytest.raises(ConfigError, match="quality"):
        _write(tmp_path, bad)


def test_ethnicity_and_religion_can_never_be_protected_keys() -> None:
    for bad in ({"group": "ethnicity"}, {"Dan-Toc": "k"}, {"faith": "x"}, {"g": " Religion "}):
        with pytest.raises(ValueError):
            MonitorBindings.model_validate(
                {"fairness": {"decision_tool": "d", "protected_attribute_keys": bad}}
            )
    for name in ("ethnicity", "Religion", "dan_toc"):
        with pytest.raises(ValueError):
            MonitorBindings.model_validate(
                {"fairness": {"decision_tool": "d", "protected_attribute_keys": {name: "k"}}}
            )
    ok = MonitorBindings.model_validate(
        {"fairness": {"decision_tool": "d", "protected_attribute_keys": {"Gender": "g"}}}
    )
    assert ok.fairness is not None and ok.fairness.protected_attribute_keys == {"gender": "g"}


def test_demo_agents_keep_their_legacy_bindings() -> None:
    """Defaults derived from the tool classes reproduce the three hard-coded demo tools."""
    res = BindingResolver()
    assert res.resolve("customer_service").quality.reply_tools == ("reply",)
    assert res.resolve("credit_prequal").fairness.decision_tool == "decide_prequal"
    assert res.resolve("payments").split.tool == "transfer"
    assert not res.resolve("payments").fairness.bound  # no credit tool: not applicable


def test_policy_schema_accepts_monitors() -> None:
    doc = PolicyDoc.model_validate(
        {
            "policy_version": 1,
            "agents": {
                "a": {
                    "name": "A",
                    "owner_user": "u",
                    "owner_team": "t",
                    "monitors": {"quality": {"reply_tools": ["r"]}},
                }
            },
        }
    )
    assert doc.agents["a"].monitors is not None
    assert (REPO_ROOT / "policies" / "schema.json").read_text().count("monitors") >= 1


# ------------------------------------------------------------------------ status rows


def test_status_row_is_idempotent_and_merges(adapters, clock, evidence) -> None:  # noqa: ANN001
    from supervisor.monitors.common import MonitorContext

    ctx = MonitorContext.from_adapters(adapters, evidence)
    day = clock.now().date()
    assert set_status(ctx, day, "x", "quality", NOT_APPLICABLE, code="no_binding", reason="r")
    assert not set_status(ctx, day, "x", "quality", NOT_APPLICABLE, code="no_binding", reason="r")
    assert set_status(ctx, day, "x", "drift", NO_DATA, code="collecting_baseline", reason="w")
    got = read_status(ctx, day, "x")
    assert set(got) == {"quality", "drift"} and got["drift"]["status"] == NO_DATA
    with pytest.raises(ValueError):
        set_status(ctx, day, "x", "nonsense", OK)
    assert evidence.entries == []  # derived data: nothing goes on the chain


def test_from_settings_reads_policy_dir_like_the_gate(tmp_path: Path) -> None:
    """D13 x D06: with POLICY_DIR set, monitor bindings (and so the quality sweep, drift,
    fairness and multi-agent jobs) come from the same folder the gate enforces."""
    from supervisor.config import load_settings
    from supervisor.monitors.bindings import DEFAULT_POLICY_DIR

    _write(
        tmp_path,
        "policy_version: 1\nagents:\n  a1:\n    name: x\n    owner_user: u\n    owner_team: t\n"
        "    monitors:\n      quality: {reply_tools: [from_policy_dir]}\n",
    )
    settings = load_settings(
        policy_dir=tmp_path / "policies", monitor_manifest_dir=tmp_path / "agents"
    )
    r = BindingResolver.from_settings(settings).resolve("a1")
    assert (r.quality.reply_tools, r.quality.source) == (("from_policy_dir",), POLICY)
    # without POLICY_DIR the built-in folder is read, as before
    plain = BindingResolver.from_settings(load_settings(monitor_manifest_dir=tmp_path / "agents"))
    assert plain.resolve("a1").quality.reply_tools != ("from_policy_dir",)
    assert DEFAULT_POLICY_DIR == REPO_ROOT / "policies"

"""WP-G2 hooks into the task list, the control catalogue and the obligation matrix: additive for an
agent on a system, byte-identical for an agent without one or with the flag off."""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import yaml

from supervisor.controls.harness_env import CtlEnv
from supervisor.controls.refs import control_scope
from supervisor.governance.rules_service import RulesService, assigned_refs
from supervisor.governance.systems import SystemService
from supervisor.tasks.model import CLASSES, LEVELS

from .conftest import draft

ADMIN = SimpleNamespace(user_id="ada", kind="user", roles=frozenset({"admin"}))


def _rules_file(tmp_path: Path, **assign: Any) -> Path:
    path = tmp_path / "rules.yaml"
    path.write_text(
        yaml.safe_dump(
            [
                {
                    "id": "AR-T",
                    "title": "test",
                    "when": {"field": "status", "in": ["draft", "active"]},
                    "assign": assign,
                }
            ]
        ),
        encoding="utf-8",
    )
    return path


def _env(tmp_path: Path, *, flag: bool, **assign: Any) -> CtlEnv:
    env = CtlEnv()
    env.settings.governance_enabled = flag
    env.settings.assignment_rules_config = _rules_file(
        tmp_path, **(assign or {"controls": ["CTL-X"]})
    )
    return env


def _system_for(env: CtlEnv, agent: str, **over: Any) -> str:
    svc = SystemService.from_adapters(env.adapters)
    s = svc.register(draft(**over), "owner.lan")
    svc.link(s["system_id"], "agent", agent, "owner.lan")
    return str(s["system_id"])


def _rows(env: CtlEnv, agent: str) -> list[tuple[Any, ...]]:
    return [
        (r["stage"], r["template_id"], r["kind"], bool(r["required"]), r["level"])
        for r in env.tasks.rows_of(agent)
    ]


# ---- tasks ------------------------------------------------------------------------------------


def test_assigned_task_templates_join_the_task_set_and_sizing_stays_the_floor(
    tmp_path: Path,
) -> None:
    env = _env(tmp_path, flag=True, tasks=["INI-D33"])
    try:
        env.agent("pay")
        env.classify("pay", "not_high_risk", tier="low")  # INI-D33 is for unclassified only
        env.tasks.generate("pay", ADMIN)
        before = {t for _, t, *_ in _rows(env, "pay")}
        assert "INI-D33" not in before and "INI-REGISTER" in before
        _system_for(env, "pay")
        env.tasks.generate("pay", ADMIN)
        after = _rows(env, "pay")
        ids = {t for _, t, *_ in after}
        assert "INI-D33" in ids and before <= ids  # added, nothing removed
        assert env.tasks.agent_summary("pay")["generated"] is True
    finally:
        env.close()


def test_no_system_or_flag_off_gives_the_same_task_set(tmp_path: Path) -> None:
    runs = {}
    for name, flag, linked in (
        ("off", False, False),
        ("on", True, False),
        ("off-linked", False, True),
    ):
        env = _env(tmp_path, flag=flag, tasks=["INI-D33", "DES-D33"])
        try:
            env.agent("pay")
            env.classify("pay", "not_high_risk", tier="low")
            if linked:
                _system_for(env, "pay")
            env.tasks.generate("pay", ADMIN)
            runs[name] = (
                _rows(env, "pay"),
                json.dumps(
                    {
                        k: v
                        for k, v in env.tasks.agent_summary("pay").items()
                        if k not in ("tasks",)
                    },
                    sort_keys=True,
                    default=str,
                ),
            )
        finally:
            env.close()
    assert runs["off"] == runs["on"] == runs["off-linked"]


def test_preview_is_unchanged_for_every_class_and_band(tmp_path: Path) -> None:
    # `preview` is the pure plan (docs, harness, CLI); the hook does not touch it
    on = _env(tmp_path, flag=True, tasks=["INI-D33"])
    off = _env(tmp_path, flag=False, tasks=["INI-D33"])
    try:
        for cls in CLASSES:
            for band in LEVELS:
                assert on.tasks.preview(cls, band) == off.tasks.preview(cls, band)
    finally:
        on.close()
        off.close()


# ---- controls ---------------------------------------------------------------------------------


def test_assigned_control_joins_the_scope_of_the_agents_of_the_system(tmp_path: Path) -> None:
    env = _env(tmp_path, flag=True, controls=["CTL-X"])
    try:
        env.agent("pay")
        env.agent("svc")
        env.control("CTL-X", agents=["svc"], evidence=(("rule", "SVC-01"),))  # svc only
        assert [c["control_id"] for c in env.controls.controls_for("pay")] == []
        assert control_scope(env.adapters.state, "CTL-X", env.settings) == ["svc"]
        _system_for(env, "pay")
        assert [c["control_id"] for c in env.controls.controls_for("pay")] == ["CTL-X"]
        assert [c["control_id"] for c in env.controls.controls_for("svc")] == ["CTL-X"]
        assert control_scope(env.adapters.state, "CTL-X", env.settings) == ["pay", "svc"]
        comp = env.controls.agent_compliance("pay")
        assert comp["in_scope"] == 1 and comp["controls"][0]["control_id"] == "CTL-X"
        # the old two-argument call is unchanged
        assert control_scope(env.adapters.state, "CTL-X") == ["svc"]
    finally:
        env.close()


def test_a_control_for_all_agents_keeps_its_star(tmp_path: Path) -> None:
    env = _env(tmp_path, flag=True, controls=["CTL-X"])
    try:
        env.agent("pay")
        env.control("CTL-X", agents=["*"], evidence=(("pack", "pack_a"),))
        _system_for(env, "pay")
        assert control_scope(env.adapters.state, "CTL-X", env.settings) == ["*"]
    finally:
        env.close()


def test_controls_are_byte_identical_for_an_agent_without_a_system(tmp_path: Path) -> None:
    out = []
    for flag in (False, True):
        env = _env(tmp_path, flag=flag, controls=["CTL-X"], obligations=["OB-1"])
        try:
            env.agent("pay")
            env.agent("other")
            env.control("CTL-X", agents=["pay"], covers=(("matrix", "OB-1"),))
            _system_for(env, "other")  # a system exists, but not for "pay"
            comp = env.controls.agent_compliance("pay")
            comp.pop("controls")
            out.append(
                json.dumps(
                    {
                        "ids": [c["control_id"] for c in env.controls.controls_for("pay")],
                        "comp": comp,
                        "cov": env.controls.obligation_coverage("pay"),
                    },
                    sort_keys=True,
                    default=str,
                )
            )
        finally:
            env.close()
    assert out[0] == out[1]
    assert '"source"' not in out[1]


# ---- the obligation matrix --------------------------------------------------------------------


def test_assigned_obligations_show_with_source_rule(tmp_path: Path) -> None:
    env = _env(tmp_path, flag=True, controls=["CTL-X"], obligations=["OB-1", "OB-9"])
    try:
        env.agent("pay")
        env.control("CTL-X", agents=["pay"], covers=(("matrix", "OB-1"),))
        sid = _system_for(env, "pay")
        cov = {r["obligation"]: r for r in env.controls.obligation_coverage("pay")}
        assert cov["OB-1"]["source"] == "control+rule" and cov["OB-1"]["controls"] == ["CTL-X"]
        assert cov["OB-9"] == {
            "obligation": "OB-9",
            "status": "no_data",
            "controls": [],
            "source": "rule",
            "systems": [sid],
        }
        rows = RulesService.from_adapters(env.adapters).obligations(sid)
        assert [(r["obligation"], r["source"], r["rules"]) for r in rows] == [
            ("OB-1", "rule", ["AR-T"]),
            ("OB-9", "rule", ["AR-T"]),
        ]
        assert next(r for r in rows if r["obligation"] == "OB-1")["controls"] == ["CTL-X"]
    finally:
        env.close()


def test_readers_return_nothing_with_the_flag_off(tmp_path: Path) -> None:
    env = _env(tmp_path, flag=True, controls=["CTL-X"])
    try:
        env.agent("pay")
        _system_for(env, "pay")
        assert assigned_refs(env.adapters.state, env.settings, "pay", "control") == {
            "CTL-X": [_sid(env)]
        }
        env.settings.governance_enabled = False
        assert assigned_refs(env.adapters.state, env.settings, "pay", "control") == {}
    finally:
        env.close()


def _sid(env: CtlEnv) -> str:
    return str(env.adapters.state.query("ai_system")[0]["system_id"])


def test_an_archived_system_assigns_nothing_to_its_agents(tmp_path: Path) -> None:
    env = _env(tmp_path, flag=True, controls=["CTL-X"])
    try:
        env.agent("pay")
        sid = _system_for(env, "pay")
        SystemService.from_adapters(env.adapters).archive(sid, "owner.lan")
        assert assigned_refs(env.adapters.state, env.settings, "pay", "control") == {}
    finally:
        env.close()


def test_hooks_do_not_import_a_store_or_a_model() -> None:
    import ast

    banned = {"sqlite3", "httpx", "databricks", "openai", "subprocess"}
    root = Path(__file__).resolve().parents[2] / "src" / "supervisor" / "governance"
    for name in (
        "conditions",
        "rules",
        "rules_service",
        "decision33",
        "classification",
        "rules_routes",
    ):
        tree = ast.parse((root / f"{name}.py").read_text(encoding="utf-8"))
        mods = {
            (n.module or "").split(".")[0]
            if isinstance(n, ast.ImportFrom)
            else a.name.split(".")[0]
            for n in ast.walk(tree)
            if isinstance(n, (ast.Import, ast.ImportFrom))
            for a in (n.names if isinstance(n, ast.Import) else [None])
        }
        assert not (mods & banned), (name, mods & banned)
        calls = {
            n.func.id
            for n in ast.walk(tree)
            if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)
        }
        assert not (calls & {"exec", "eval", "compile"}), name

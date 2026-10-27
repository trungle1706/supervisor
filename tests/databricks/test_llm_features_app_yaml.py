"""WP-L1: app.yaml switches every model-backed feature on (AI Gateway model service)."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import httpx
import yaml

from supervisor.adapters.guard import make_guard_model
from supervisor.adapters.guard.chat import ChatGuard
from supervisor.config import Settings, load_settings
from supervisor.databricks.serving import DatabricksServingChat
from tests.conftest import REPO_ROOT
from tests.detectors.conftest import (  # noqa: F401 - pytest fixtures
    GatewayFactory,
    adapters,
    baseline,
    clock,
    evidence,
    gateway,
    make_gate,
    make_gateway,
    masker,
)

APP = REPO_ROOT / "app.yaml"
MODEL = "cat.sch.glm-5"
MONEY = {"amount_minor": 1000, "from_account_id": "ACC-1", "payee_id": "P-1", "customer_id": "C-1"}


def _apply(monkeypatch: Any, *, mock: bool = False) -> Settings:
    for e in yaml.safe_load(APP.read_text(encoding="utf-8"))["env"]:
        v = e.get("value") or "wh01"
        for a, b in (
            ("FILL-ME-workspace-host", "example-workspace.invalid"),
            ("FILL-ME-model-service", "glm-5"),
            ("FILL-ME-catalog", "cat"),
            ("FILL-ME-schema", "sch"),
            ("FILL-ME-volume", "vol"),
        ):
            v = v.replace(a, b)
        monkeypatch.setenv(e["name"], v)
    monkeypatch.setenv("DATABRICKS_HOST", "example-workspace.invalid")
    monkeypatch.setenv("DATABRICKS_CLIENT_ID", "sp-client-id")
    monkeypatch.setenv("DATABRICKS_CLIENT_SECRET", "sp-secret-value")
    monkeypatch.setenv("SUPERVISOR_ENV_FILE", "/dev/null")
    if mock:
        monkeypatch.setenv("LLM_MOCK", "1")
    else:
        monkeypatch.delenv("LLM_MOCK", raising=False)
    return load_settings()


def test_app_yaml_switches_every_model_feature_on(monkeypatch: Any) -> None:
    s = _apply(monkeypatch)
    assert s.supervisor_mode == "databricks_app" and not s.llm_mock
    assert s.llm_api_shape == "responses" and s.llm_uses_workspace_auth
    assert s.llm_model == MODEL
    assert s.judge_enabled and s.judge_t1_model == MODEL
    assert s.classifier_ai_prefill
    assert s.onboard_advisor_enabled and s.onboard_compliance_enabled
    assert s.console_integration_enabled and s.console_compliance_enabled
    assert s.redteam_attacker_model == MODEL
    assert s.guard_model_adapter == "chat"
    cfg = Path(s.detectors_config)
    assert cfg.name == "detectors.databricks.yaml"
    assert (REPO_ROOT / "config" / cfg.name).exists()


def test_databricks_detectors_file_only_differs_by_the_model_detectors() -> None:
    d = yaml.safe_load((REPO_ROOT / "config/detectors.databricks.yaml").read_text("utf-8"))
    base = yaml.safe_load((REPO_ROOT / "config/detectors.yaml").read_text("utf-8"))
    for name in ("judge_advisory", "judge_moderation", "guard_model"):
        e = d["detectors"][name]
        assert e["enabled"] is True and e["fail_closed"] is False
        assert e["mrm_status"] == base["detectors"][name]["mrm_status"]
    assert d["detectors"]["judge_moderation"]["settings"]["toxicity"]["enabled"] is True
    assert d["detectors"]["guard_model"]["settings"]["pause_tool_classes"] == []
    for name in set(base["detectors"]) - {"judge_advisory", "judge_moderation", "guard_model"}:
        assert d["detectors"][name] == base["detectors"][name], name
    assert base["detectors"]["judge_advisory"]["enabled"] is False  # defaults unchanged


def test_guard_chat_over_the_gateway_uses_app_identity_and_responses(monkeypatch: Any) -> None:
    s = _apply(monkeypatch)

    class Cfg:
        @staticmethod
        def authenticate() -> dict[str, str]:
            return {"Authorization": "Bearer app-token"}

    class Client:
        config = Cfg()

    g = make_guard_model(s, client=Client(), agent_families={"a": {"anthropic"}})
    assert isinstance(g, ChatGuard)
    inner = [v for v in vars(g).values() if isinstance(v, DatabricksServingChat)]
    assert inner and inner[0].api_shape == "responses" and inner[0].model_id == MODEL
    assert inner[0].base_url == "https://example-workspace.invalid/ai-gateway/mlflow/v1"
    assert httpx  # transport is exercised in tests/databricks serving tests


def test_with_llm_mock_the_stack_builds_and_a_money_call_is_not_blocked(
    monkeypatch: Any,
    make_gateway: GatewayFactory,  # noqa: F811
    masker: Any,  # noqa: F811
) -> None:
    s = _apply(monkeypatch, mock=True)
    assert s.llm_mock
    from supervisor.adapters.factory import make_chat_model, make_judge_chat_model

    assert "mock" in make_judge_chat_model(s, "t1").model_id
    make_chat_model(s)
    assert make_guard_model(s).is_mock is True
    text = (REPO_ROOT / "config/detectors.databricks.yaml").read_text("utf-8")
    gw = make_gateway(gate=make_gate(masker, config_text=text))
    r = gw.check("payments", "1", "transfer", MONEY, {})
    assert r["allow"] is True and r["agent_paused"] is False

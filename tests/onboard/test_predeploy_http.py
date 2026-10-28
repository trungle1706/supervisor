"""WP-O3b: the pre-deploy packs against a running candidate over its HTTP chat endpoint.

The candidate is a FastAPI stub (tests/assurance/http_stub.py) behind a TestClient transport: no
socket is opened (``no_network``). The stored tree is a small kb-chatbot look-alike with an
``http_target`` block in ``supervisor.manifest.yaml``."""

from __future__ import annotations

import json
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest

from supervisor.adapters.factory import Adapters, build_adapters
from supervisor.config import load_settings
from supervisor.jobs import bootstrap_schema
from supervisor.onboard import predeploy
from supervisor.onboard.predeploy import PredeployService
from tests.assurance.http_stub import asgi_transport, fake_auth, make_app
from tests.onboard.test_facts import make_zip

pytestmark = pytest.mark.usefixtures("no_network")

NODE = "kb-chatbot"
HOST = "kb-chatbot.example.invalid"
MANIFEST = f"""manifest_version: 1
system:
  name: Bank knowledge chatbot (synthetic)
agent:
  agent_id: kb_chatbot
  name: Bank knowledge chatbot
http_target:
  url: https://{HOST}
  path: /chat
  message_field: question
  session_field: ""
  history_field: history
  answer_field: answer
"""
REQUIREMENTS = "fastapi==0.115.0\nuvicorn==0.30.6\npydantic==2.9.2\n"
CODE = '"""KB chatbot look-alike (synthetic)."""\n\nAGENT_ID = "kb_chatbot"\n'


@pytest.fixture(autouse=True)
def _no_leftover_runs() -> Iterator[None]:
    predeploy._RUNNING.clear()
    yield
    for th in list(predeploy._THREADS.values()):
        th.join(30)
    predeploy._RUNNING.clear()
    predeploy._THREADS.clear()


def make_adapters(tmp_path: Path, **flags: Any) -> Adapters:
    base: dict[str, Any] = {
        "sql_backend": "sqlite",
        "data_dir": tmp_path / "data",
        "llm_base_url": "",
        "onboard_intake": True,
        "onboard_facts": True,
        "onboard_predeploy": True,
        "predeploy_http_target": True,
        "predeploy_http_allowed_hosts": HOST,
        "predeploy_http_max_turns": 50,
    }
    base.update(flags)
    a = build_adapters(load_settings(**base))
    bootstrap_schema.run(a.settings, a)
    return a


@pytest.fixture
def adapters(tmp_path: Path) -> Iterator[Adapters]:
    a = make_adapters(tmp_path)
    try:
        yield a
    finally:
        a.close()


def take_in_tree(a: Adapters, manifest: str = MANIFEST) -> int:
    from supervisor.onboard.intake import IntakeService

    entries = {
        "supervisor.manifest.yaml": manifest,
        "requirements.txt": REQUIREMENTS,
        "agent.py": CODE,
    }
    return int(
        IntakeService(a.settings, a.state, a.clock).submit_zip(
            NODE, make_zip(entries), "s.zip", "reviewer.an"
        )["n"]
    )


def service(a: Adapters, calls: list[dict[str, Any]] | None = None, **kw: Any) -> PredeployService:
    app = kw.pop("app", None) or make_app()
    return PredeployService(
        a.settings,
        a.state,
        a.clock,
        http_transport=kw.pop("transport", None) or asgi_transport(app, calls),
        http_auth=fake_auth,
        **kw,
    )


def run(a: Adapters, s: PredeployService) -> dict[str, Any]:
    n = take_in_tree(a)
    return s.start(NODE, n, "reviewer.an", background=False)


def packs_of(rep: dict[str, Any]) -> dict[str, dict[str, str]]:
    return {i["id"]: i for i in rep["items"] if i["section"] == "packs"}


# ------------------------------------------------------------------------------ wiring


def test_the_chat_packs_run_against_the_http_target(adapters: Adapters) -> None:
    calls: list[dict[str, Any]] = []
    rep = run(adapters, service(adapters, calls))
    packs = packs_of(rep)
    assert calls, "no turn reached the stub"
    # the request shape follows the block: question + history, no session id
    assert all("question" in c["payload"] and "session_id" not in c["payload"] for c in calls)
    assert all(c["url"] == f"https://{HOST}/chat" for c in calls)
    chat_packs = [
        p for k, p in packs.items() if k.startswith("pack:") and "target: http" in p["text"]
    ]
    assert len(chat_packs) >= 6
    for p in chat_packs:
        assert f"[target: http {HOST}" in p["text"]
    assert "packs:no_harness" not in packs  # the WP-O3 "no harness" warning is gone
    assert "FAKE-SP-TOKEN" not in json.dumps(rep)  # the auth header never reaches the report
    # a pack that needs the sandbox gate cannot pass over chat: a fail, never a quiet pass
    assert packs["pack:owasp_agentic_redteam"]["status"] == "fail"


def test_the_multiturn_item_names_the_http_target(adapters: Adapters) -> None:
    rep = run(adapters, service(adapters))
    mt = [i for i in rep["items"] if i["section"] == "multiturn"]
    assert len(mt) == 1 and f"[target: http {HOST}" in mt[0]["text"]
    assert mt[0]["status"] in ("ok", "warn", "skip")  # advisory: never fail


def test_no_block_or_flag_off_keeps_the_wp_o3_behaviour(tmp_path: Path) -> None:
    for flags in ({"predeploy_http_target": False}, {"predeploy_http_allowed_hosts": ""}):
        a = make_adapters(tmp_path / str(len(flags) + len(str(flags))), **flags)
        try:
            calls: list[dict[str, Any]] = []
            rep = run(a, service(a, calls))
            packs = packs_of(rep)
            assert calls == []
            assert packs["packs:no_harness"]["status"] == "warn"
            assert any("[target: no harness]" in i["text"] for i in packs.values())
            assert not any("target: http" in i["text"] for i in rep["items"])
            assert "packs:http_target" not in packs and rep["verdict"] == "no_go"
        finally:
            a.close()


def test_a_tree_without_a_block_uses_no_harness(adapters: Adapters) -> None:
    n = take_in_tree(adapters, MANIFEST.split("http_target:")[0])
    calls: list[dict[str, Any]] = []
    rep = service(adapters, calls).start(NODE, n, "reviewer.an", background=False)
    assert calls == [] and "packs:no_harness" in packs_of(rep)


def test_a_refused_block_is_a_fail_item_and_no_turn_is_sent(adapters: Adapters) -> None:
    calls: list[dict[str, Any]] = []
    bad = MANIFEST.replace(HOST, "evil.example.invalid")
    n = take_in_tree(adapters, bad)
    rep = service(adapters, calls).start(NODE, n, "reviewer.an", background=False)
    item = packs_of(rep)["packs:http_target"]
    assert item["status"] == "fail" and "not in PREDEPLOY_HTTP_ALLOWED_HOSTS" in item["text"]
    assert calls == [] and rep["verdict"] == "no_go"


def test_an_inventory_system_node_with_an_allowed_url_is_enough(adapters: Adapters) -> None:
    n = take_in_tree(adapters, "manifest_version: 1\n")
    now = adapters.clock.now()
    adapters.state.insert(
        "inventory_node",
        {
            "node_id": NODE,
            "kind": "system",
            "name": NODE,
            "display_name": NODE,
            "status": "active",
            "own_risk": None,
            "risk_source": "none",
            "decision33_class": None,
            "attrs": json.dumps({"url": f"https://{HOST}"}),
            "evidence": "[]",
            "first_seen": now,
            "last_seen": now,
        },
    )
    calls: list[dict[str, Any]] = []
    # default field names (message / session_id) and path /chat: the stub wants `question`,
    # so the turns are refused with HTTP 422; the point here is that the target is used
    rep = service(adapters, calls).start(NODE, n, "reviewer.an", background=False)
    assert calls and "message" in calls[0]["payload"] and "session_id" in calls[0]["payload"]
    assert any(f"target: http {HOST}" in i["text"] for i in rep["items"])


# ------------------------------------------------------------------------------ RUNNING


def set_state(a: Adapters, state: str) -> None:
    now = a.clock.now()
    a.state.insert(
        "agent",
        {
            "agent_id": "kb_chatbot",
            "name": "kb",
            "owner_team": "t",
            "owner_user": "u",
            "business_owner": None,
            "risk_tier": "low",
            "decision33_class": None,
            "host_type": "http",
            "plug_point": "sdk",
            "model_family": "qwen",
            "status": "active",
            "gate_state": state,
            "created_at": now,
        },
    )


def test_a_running_agent_gets_a_warn_item(adapters: Adapters) -> None:
    set_state(adapters, "RUNNING")
    packs = packs_of(run(adapters, service(adapters)))
    item = packs["packs:running_agent"]
    assert item["status"] == "warn" and "assessment ran against a RUNNING agent" in item["text"]


def test_a_shadow_agent_gets_no_warn_item(adapters: Adapters) -> None:
    set_state(adapters, "SHADOW")
    assert "packs:running_agent" not in packs_of(run(adapters, service(adapters)))


# ------------------------------------------------------------------------------ the proof


def test_the_verdict_comes_from_real_pack_results_not_from_no_harness(tmp_path: Path) -> None:
    """Same tree, flag off then on. Off: the chat packs fail with 'no harness'. On: they are
    computed from the answers of the stub, and the pack items carry the HTTP target label."""
    off = make_adapters(tmp_path / "off", predeploy_http_target=False)
    on = make_adapters(tmp_path / "on", predeploy_http_max_turns=500)
    try:
        r_off = run(off, service(off))
        r_on = run(on, service(on))
    finally:
        off.close()
        on.close()
    p_off, p_on = packs_of(r_off), packs_of(r_on)
    assert r_off["verdict"] == "no_go"
    chat = ("truthfulqa_vi", "pii_canary", "finance_harm_refusal", "perturbation_vi")
    for pid in chat:
        t = p_off[f"pack:{pid}"]
        assert t["status"] == "fail" and "no harness" in t["text"] and "capab" in t["text"]
        assert "capabilit" not in p_on[f"pack:{pid}"]["text"]
    # computed from the stub answers: the stub never repeats a planted value, so these pass ...
    for pid in ("pii_canary", "perturbation_vi", "counterfactual_vi"):
        item = p_on[f"pack:{pid}"]
        assert (
            item["status"] == "ok" and "turns]" in item["text"] and " 0 turns" not in item["text"]
        )
    # ... and it cannot know the truthful answers: a real metric misses its limit
    assert p_on["pack:truthfulqa_vi"]["status"] == "fail"
    assert "truthful_bp=" in p_on["pack:truthfulqa_vi"]["text"]
    # packs that need tools or the sandbox gate cannot run over chat: still fail, with the reason
    for pid in ("owasp_agentic_redteam", "indirect_injection_vi", "mcp_tool_manifest_drift"):
        assert p_on[f"pack:{pid}"]["status"] == "fail" and "capab" in p_on[f"pack:{pid}"]["text"]
    assert r_on["verdict"] == "no_go"


def test_the_default_turn_cap_stops_a_pack_with_an_error_item(adapters: Adapters) -> None:
    packs = packs_of(run(adapters, service(adapters)))  # the settings cap is 50 turns per pack
    item = packs["pack:perturbation_vi"]
    assert item["status"] == "fail" and "TurnLimitError" in item["text"]
    assert "turn cap 50 reached" in item["text"]


def test_a_dead_candidate_gives_error_items_not_a_crash(adapters: Adapters) -> None:
    transport = asgi_transport(make_app(), fail_with=ConnectionError("down"))
    rep = run(adapters, service(adapters, transport=transport))
    packs = packs_of(rep)
    assert (
        packs["pack:pii_canary"]["status"] == "fail"
        and "ConnectionError" in packs["pack:pii_canary"]["text"]
    )
    assert rep["status"] == "done" and rep["verdict"] == "no_go"

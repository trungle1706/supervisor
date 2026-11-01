"""W6 (GUARDIAN_KIT): the generated ``guardian_client.py`` against the REAL gate route.

The file is written to a temporary folder and imported (no exec, no eval). Its request builder and
its HTTP gate then talk to ``/v1/gate/check`` of the real app through the FastAPI TestClient, with
ingress authentication on: allow, block (a real rule), HMAC verification (good key, wrong key, no
key, a body changed after signing), the Databricks bearer path (fake identity verifier, labelled
fake), and the fail-closed rules."""

from __future__ import annotations

import asyncio
import importlib.util
from collections.abc import Callable, Iterator, Mapping
from pathlib import Path
from types import ModuleType
from typing import Any
from urllib.parse import urlparse

import pytest
from fastapi.testclient import TestClient

from supervisor.adapters.auth.agent_creds_identity import AgentIdentityMap, FakeIdentityVerifier
from supervisor.app import app
from supervisor.config import Settings, load_settings
from supervisor.gateway import ingress_auth, wiring
from supervisor.gateway.ingress_auth import main as ingress_cli
from supervisor.gateway.ingress_sign import compute_signature, string_to_sign
from supervisor.onboard import guardian_kit as gk
from supervisor.wiring import Runtime, build_runtime

AGENT = "customer_service"
TABLE = {"read_ticket": "read_only", "ext_transfer_api": "money"}  # tools of the default policy


def to_testclient(client: TestClient) -> Callable[[str, bytes, Mapping[str, str], float], Any]:
    """Transport of the generated client: the exact bytes go to the in-process app."""

    def transport(url: str, body: bytes, headers: Mapping[str, str], timeout: float) -> Any:
        r = client.post(urlparse(url).path, content=body, headers=dict(headers))
        if r.status_code >= 400:
            err = RuntimeError(f"http {r.status_code}")
            err.response = r  # type: ignore[attr-defined]
            raise err
        return r.json()

    return transport


@pytest.fixture
def mod(tmp_path: Path) -> ModuleType:
    """The generated file for AGENT, imported from disk."""
    path = tmp_path / "gen" / "guardian_client.py"
    path.parent.mkdir()
    path.write_text(gk.client_source(AGENT, "1.0.0", TABLE), encoding="utf-8")
    spec = importlib.util.spec_from_file_location("guardian_client_gen", path)
    assert spec is not None and spec.loader is not None
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def _runtime(settings: Settings) -> Iterator[Runtime]:
    rt = build_runtime(settings, policy_refresh_s=0.0)
    wiring.set_gateway(rt.gateway)
    try:
        yield rt
    finally:
        ingress_auth.set_guard(None)
        wiring.set_gateway(None)
        rt.close()


@pytest.fixture
def laptop(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> Iterator[tuple[Runtime, str]]:
    keys = tmp_path / "agent_keys.yaml"
    key_out = tmp_path / "customer.key"
    rc = ingress_cli(["issue", AGENT, "--keys-file", str(keys), "--out-key-file", str(key_out)])
    capsys.readouterr()
    assert rc == 0
    settings = load_settings(
        supervisor_mode="laptop",
        sql_backend="sqlite",
        data_dir=tmp_path / "data",
        llm_base_url="",
        ingress_auth_enabled=True,
        ingress_keys_file=keys,
    )
    for rt in _runtime(settings):
        ingress_auth.set_guard(ingress_auth.build_guard(settings))
        yield rt, str(key_out)


@pytest.fixture
def databricks_fake(tmp_path: Path) -> Iterator[Runtime]:
    ids = tmp_path / "agent_identities.yaml"
    ids.write_text(
        f"principals:\n  - principal: fake-sp-app-id\n    agents: [{AGENT}]\n", encoding="utf-8"
    )
    settings = load_settings(
        supervisor_mode="databricks_app",
        sql_backend="sqlite",
        data_dir=tmp_path / "data",
        llm_base_url="",
        ingress_auth_enabled=True,
        ingress_identities_file=ids,
        ingress_credential_kind="databricks_sp",
        databricks_host="https://fake-workspace.invalid",
    )
    for rt in _runtime(settings):
        guard = ingress_auth.build_guard(settings)
        assert guard.verifier is not None
        guard.verifier.identity = FakeIdentityVerifier({"fake-token": "fake-sp-app-id"})
        guard.verifier.identities = AgentIdentityMap.from_file(ids)
        ingress_auth.set_guard(guard)
        yield rt


# ------------------------------------------------------------------------------ the signature


def test_signature_text_is_the_text_of_the_server(mod: ModuleType) -> None:
    args = (AGENT, "1700000000", "n" * 24, "post", "/v1/gate/check", "ab" * 32)
    assert mod.string_to_sign(*args) == string_to_sign(*args)
    body = b'{"a":1}'
    secret = "s" * 40
    got = mod.sign(secret, AGENT, "1700000000", "n" * 24, "POST", "/v1/gate/check", body)
    assert got == compute_signature(
        secret, AGENT, "1700000000", "n" * 24, "POST", "/v1/gate/check", body
    )


def test_request_builder_signs_the_exact_bytes(mod: ModuleType) -> None:
    cred = mod.HmacCredential(AGENT, "k" * 40, clock=lambda: 1_700_000_000)
    url, body, headers = mod.build_request(
        "https://g.example/", AGENT, "1.0.0", "read_ticket", {"ticket_id": "T1"}, {"x": 1}, cred
    )
    assert url == "https://g.example/v1/gate/check"
    assert headers["Content-Type"] == "application/json" and headers["X-Supervisor-Agent"] == AGENT
    want = compute_signature(
        "k" * 40,
        AGENT,
        headers["X-Supervisor-Timestamp"],
        headers["X-Supervisor-Nonce"],
        "POST",
        "/v1/gate/check",
        body,
    )
    assert headers["X-Supervisor-Signature"] == want
    # an address that already ends in /v1 posts to /gate/check, as the full SDK does
    assert mod.build_request("https://g.example/v1", AGENT, "1", "t", {}, None)[0].endswith(
        "/v1/gate/check"
    )


# ------------------------------------------------------------------------------ the real gate


def test_hmac_allow_and_block_against_the_real_route(
    laptop: tuple[Runtime, str], mod: ModuleType
) -> None:
    rt, key_file = laptop
    client = TestClient(app)
    import os

    os.chmod(key_file, 0o600)
    cred = mod.HmacCredential(AGENT, Path(key_file).read_text().splitlines()[0].strip())
    gate = mod.HttpGate("http://testserver", cred, transport=to_testclient(client))
    calls: list[str] = []

    @mod.supervised_tool("read_ticket", gate=gate)
    def read_ticket(ticket_id: str) -> str:
        calls.append("read")
        return "ok " + ticket_id

    @mod.supervised_tool("ext_transfer_api", gate=gate)
    def ext_transfer_api(amount_minor: int) -> str:
        calls.append("pay")
        return "paid"

    assert read_ticket("T1") == "ok T1"  # a real allow
    with pytest.raises(mod.SupervisorBlocked) as blocked:
        ext_transfer_api(1)  # a real rule (SVC-07) says no
    assert blocked.value.decision["rule_id"] == "SVC-07"
    assert calls == ["read"]  # the blocked tool never ran
    counts = rt.gateway.metrics.snapshot()["counts"]
    assert counts["ingress_accepted"] >= 2


def test_async_tools_are_gated_the_same_way(laptop: tuple[Runtime, str], mod: ModuleType) -> None:
    _, key_file = laptop
    import os

    os.chmod(key_file, 0o600)
    cred = mod.HmacCredential(AGENT, Path(key_file).read_text().splitlines()[0].strip())
    gate = mod.HttpGate("http://testserver", cred, transport=to_testclient(TestClient(app)))

    @mod.supervised_tool("read_ticket", gate=gate)
    async def read_ticket(ticket_id: str) -> str:
        return "async " + ticket_id

    @mod.supervised_tool(
        AGENT, "1.0.0", "ext_transfer_api", "money", gate=gate
    )  # the full SDK form
    async def ext_transfer_api(amount_minor: int) -> str:
        return "paid"

    assert asyncio.run(read_ticket("T2")) == "async T2"
    with pytest.raises(mod.SupervisorBlocked):
        asyncio.run(ext_transfer_api(5))


def test_wrong_key_no_key_and_changed_body_are_refused(
    laptop: tuple[Runtime, str], mod: ModuleType
) -> None:
    _, key_file = laptop
    import os

    os.chmod(key_file, 0o600)
    client = TestClient(app)
    good = mod.HmacCredential(AGENT, Path(key_file).read_text().splitlines()[0].strip())
    tc = to_testclient(client)
    wrong = mod.HttpGate("http://testserver", mod.HmacCredential(AGENT, "w" * 48), transport=tc)
    none = mod.HttpGate("http://testserver", None, transport=tc)
    ctx = {"declared_risk_class": "read_only"}
    for gate in (wrong, none):  # a refused credential is closed, even for a read-only tool
        d = gate.check(AGENT, "1.0.0", "read_ticket", {"ticket_id": "T"}, ctx)
        assert d["allow"] is False and d["rule_id"] == "GATE-AUTH"
    # a body changed after it was signed does not verify
    url, body, headers = mod.build_request(
        "http://testserver", AGENT, "1.0.0", "read_ticket", {"ticket_id": "T"}, ctx, good
    )
    ok = client.post(urlparse(url).path, content=body, headers=headers)
    assert ok.status_code == 200 and ok.json()["allow"] is True
    _, body2, headers2 = mod.build_request(
        "http://testserver", AGENT, "1.0.0", "read_ticket", {"ticket_id": "T"}, ctx, good
    )
    tampered = client.post(
        urlparse(url).path, content=body2.replace(b'"T"', b'"X"'), headers=headers2
    )
    assert tampered.status_code == 401
    replay = client.post(urlparse(url).path, content=body, headers=headers)  # same nonce again
    assert replay.status_code == 401
    # a key may not speak for another agent
    other = mod.HttpGate("http://testserver", good, transport=tc).check(
        "payments", "1", "get_balance", {}, ctx
    )
    assert other["rule_id"] == "GATE-AUTH"


def test_databricks_bearer_path_against_the_real_route(
    databricks_fake: Runtime, mod: ModuleType
) -> None:
    client = TestClient(app)
    tc = to_testclient(client)
    seen: list[str] = []

    def headers() -> dict[str, str]:  # what Config().authenticate() returns; asked on every call
        seen.append("asked")
        return {"Authorization": "Bearer fake-token"}

    cred = mod.BearerCredential(AGENT, headers)
    gate = mod.HttpGate("http://testserver", cred, transport=tc)
    ctx = {"declared_risk_class": "read_only"}
    assert gate.check(AGENT, "1.0.0", "read_ticket", {"ticket_id": "T"}, ctx)["allow"] is True
    assert (
        gate.check(AGENT, "1.0.0", "ext_transfer_api", {"amount_minor": 1}, {})["rule_id"]
        == "SVC-07"
    )
    assert len(seen) == 2  # the token is asked for each time, never kept
    assert "fake-token" not in repr(cred) and "fake-token" not in repr(gate.__dict__)
    bad = mod.HttpGate(
        "http://testserver",
        mod.BearerCredential(AGENT, lambda: {"Authorization": "Bearer nope"}),
        transport=tc,
    )
    assert bad.check(AGENT, "1.0.0", "read_ticket", {}, ctx)["rule_id"] == "GATE-AUTH"
    broken = mod.HttpGate(
        "http://testserver", mod.BearerCredential(AGENT, lambda: {}), transport=tc
    )
    assert broken.check(AGENT, "1.0.0", "read_ticket", {}, ctx)["rule_id"] == "GATE-AUTH"


# ------------------------------------------------------------------------------ fail closed


def _down(url: str, body: bytes, headers: Mapping[str, str], timeout: float) -> Any:
    raise ConnectionError("gateway is down")


def test_no_gate_no_call_and_only_read_only_may_pass_when_unreachable(mod: ModuleType) -> None:
    ran: list[str] = []
    gate = mod.HttpGate("http://down.invalid", None, transport=_down)

    @mod.supervised_tool("read_ticket", gate=gate)
    def read_ticket() -> str:
        ran.append("read")
        return "r"

    @mod.supervised_tool("ext_transfer_api", gate=gate)
    def pay() -> str:
        ran.append("pay")
        return "p"

    assert read_ticket() == "r"  # read only: goes on, as an alert
    assert (
        gate.check(AGENT, "1", "read_ticket", {}, {"declared_risk_class": "read_only"})["action"]
        == "alert"
    )
    with pytest.raises(mod.SupervisorBlocked) as e:
        pay()
    assert e.value.decision["rule_id"] == "GATE-UNREACHABLE" and ran == ["read"]


def test_no_guardian_address_blocks_every_tool_even_read_only(
    mod: ModuleType, monkeypatch: pytest.MonkeyPatch
) -> None:
    for name in ("GUARDIAN_URL", "SUPERVISOR_GATE_URL"):
        monkeypatch.delenv(name, raising=False)

    @mod.supervised_tool("read_ticket")
    def read_ticket() -> str:
        raise AssertionError("must not run")

    with pytest.raises(mod.SupervisorBlocked) as e:
        read_ticket()
    assert e.value.decision["rule_id"] == "GATE-MISSING"


def test_a_pause_answer_raises_paused_and_a_garbled_answer_is_closed(mod: ModuleType) -> None:
    def pause(url: str, body: bytes, headers: Mapping[str, str], timeout: float) -> Any:
        return {
            "allow": False,
            "action": "pause",
            "rule_id": "AGENT-PAUSED",
            "reason": "agent is paused",
        }

    @mod.supervised_tool("read_ticket", gate=mod.HttpGate("http://x", None, transport=pause))
    def f() -> None: ...

    with pytest.raises(mod.SupervisorPaused):
        f()

    def junk(url: str, body: bytes, headers: Mapping[str, str], timeout: float) -> Any:
        return {"allow": "yes"}

    d = mod.HttpGate("http://x", None, transport=junk).check(AGENT, "1", "ext_transfer_api", {}, {})
    assert d["allow"] is False and d["rule_id"] == "GATE-ERROR"
    d = mod.HttpGate("http://x", None, transport=junk).check(AGENT, "1", "t", {"o": object()}, {})
    assert d["rule_id"] == "GATE-ARGS"  # arguments that are not plain JSON never reach the wire


def test_a_slow_gate_hits_the_deadline_and_fails_closed(mod: ModuleType) -> None:
    import time

    def slow(url: str, body: bytes, headers: Mapping[str, str], timeout: float) -> Any:
        time.sleep(1.0)
        return {"allow": True}

    gate = mod.HttpGate("http://x", None, timeout_s=0.05, transport=slow)
    d = gate.check(AGENT, "1", "ext_transfer_api", {}, {"declared_risk_class": "money"})
    assert d["allow"] is False and d["rule_id"] == "GATE-UNREACHABLE"


def test_decorator_refuses_an_unknown_tool_and_keeps_the_signature(mod: ModuleType) -> None:
    with pytest.raises(ValueError):

        @mod.supervised_tool("not_in_the_table")
        def f() -> None: ...

    @mod.supervised_tool(
        "not_in_the_table", "money", gate=mod.HttpGate("http://x", None, transport=_down)
    )
    def g(a: int, b: str = "x") -> None:
        """doc"""

    import inspect

    assert inspect.signature(g) == inspect.signature(g.__wrapped__) and g.__doc__ == "doc"
    assert list(inspect.signature(g).parameters) == ["a", "b"]


def test_key_file_open_to_others_is_refused(
    mod: ModuleType, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import os

    key = tmp_path / "k.key"
    key.write_text("z" * 48 + "\n")
    os.chmod(key, 0o644)
    for name in ("GUARDIAN_AGENT_KEY", "SUPERVISOR_AGENT_KEY", "SUPERVISOR_AGENT_KEY_FILE"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("GUARDIAN_AGENT_KEY_FILE", str(key))
    with pytest.raises(mod.CredentialError):
        mod.credential_from_env(AGENT)
    os.chmod(key, 0o600)
    assert isinstance(mod.credential_from_env(AGENT), mod.HmacCredential)
    monkeypatch.delenv("GUARDIAN_AGENT_KEY_FILE")
    monkeypatch.setenv("GUARDIAN_AGENT_KEY", "short")
    with pytest.raises(mod.CredentialError):
        mod.credential_from_env(AGENT)


def test_main_prints_no_secret(
    mod: ModuleType, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setenv("GUARDIAN_URL", "https://g.example")
    monkeypatch.setenv("GUARDIAN_AGENT_KEY", "q" * 40)
    assert mod.main() == 0
    out = capsys.readouterr().out
    assert "[OK] guardian address: set" in out and "q" * 10 not in out and "HmacCredential" in out

"""WP20 e2e: SDK client -> real app with ingress auth on -> real gateway decision.

Two modes:
* laptop          SUPERVISOR_MODE=laptop, HMAC key from the file key store (issued by the CLI).
* databricks_fake SUPERVISOR_MODE=databricks_app, service-principal bearer token verified by the
                  FAKE identity verifier (labelled fake) and mapped by config/agent_identities.yaml.
                  The gate store is SQLite here: the Delta fake answers scripted statements only
                  and WP20 adds no table, so no Delta-specific path exists to exercise.
"""

from __future__ import annotations

from collections.abc import Callable, Iterator, Mapping
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import pytest
from fastapi.testclient import TestClient

from supervisor.adapters.auth.agent_creds_identity import AgentIdentityMap, FakeIdentityVerifier
from supervisor.app import app
from supervisor.config import Settings, load_settings
from supervisor.gateway import ingress_auth, wiring
from supervisor.gateway.ingress_auth import main as ingress_cli
from supervisor.gateway.ingress_sign import IngressCredential
from supervisor.gateway.sdk import HttpGate
from supervisor.wiring import Runtime, build_runtime

AGENT = "customer_service"


def to_testclient(client: TestClient) -> Callable[[str, bytes, Mapping[str, str], float], Any]:
    """Signed transport that sends the exact bytes to the in-process app (no socket)."""

    def transport(url: str, body: bytes, headers: Mapping[str, str], timeout: float) -> Any:
        r = client.post(urlparse(url).path, content=body, headers=dict(headers))
        if r.status_code >= 400:
            err = RuntimeError(f"http {r.status_code}")
            err.response = r  # type: ignore[attr-defined]
            raise err
        return r.json()

    return transport


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
        sql_backend="sqlite",  # see the module docstring
        data_dir=tmp_path / "data",
        llm_base_url="",
        ingress_auth_enabled=True,
        ingress_identities_file=ids,
        databricks_host="https://fake-workspace.invalid",
    )
    assert settings.effective_ingress_kind == "databricks_sp"  # the mode default
    for rt in _runtime(settings):
        guard = ingress_auth.build_guard(settings)
        assert guard.verifier is not None
        guard.verifier.identity = FakeIdentityVerifier({"fake-token": "fake-sp-app-id"})
        guard.verifier.identities = AgentIdentityMap.from_file(ids)
        ingress_auth.set_guard(guard)
        yield rt


def _decisions(gate: HttpGate) -> tuple[dict[str, Any], dict[str, Any]]:
    allowed = dict(gate.check(AGENT, "1", "read_ticket", {"ticket_id": "T1"}))
    blocked = dict(gate.check(AGENT, "1", "ext_transfer_api", {"amount_minor": 1}))
    return allowed, blocked


def test_laptop_sdk_hmac_to_gate_decision(laptop: tuple[Runtime, str]) -> None:
    rt, key_file = laptop
    client = TestClient(app)
    from supervisor.gateway.ingress_sign import credential_from_env

    cred = credential_from_env(AGENT, key_file)
    gate = HttpGate("http://testserver", credential=cred, signed_transport=to_testclient(client))
    allowed, blocked = _decisions(gate)
    assert allowed["allow"] is True
    assert blocked["allow"] is False and blocked["rule_id"] == "SVC-07"  # a real gate decision

    # an unsigned SDK and an SDK with a wrong key are refused: fail closed, rule GATE-AUTH
    unsigned = HttpGate(
        "http://testserver",
        credential=None,
        transport=lambda url, payload, t: _raise_from(
            client.post(urlparse(url).path, json=payload)
        ),
    )
    assert unsigned.check(AGENT, "1", "read_ticket", {})["rule_id"] == "GATE-AUTH"
    wrong = IngressCredential(AGENT, "w" * 48)
    bad = HttpGate("http://testserver", credential=wrong, signed_transport=to_testclient(client))
    assert bad.check(AGENT, "1", "read_ticket", {})["rule_id"] == "GATE-AUTH"
    # an agent cannot ask the gate about another agent id with its own key
    good = HttpGate("http://testserver", credential=cred, signed_transport=to_testclient(client))
    assert good.check("payments", "1", "get_balance", {})["rule_id"] == "GATE-AUTH"
    counts = rt.gateway.metrics.snapshot()["counts"]
    assert counts["ingress_rejected"] == 3 and counts["ingress_accepted"] >= 2


def _raise_from(resp: Any) -> Any:
    if resp.status_code >= 400:
        err = RuntimeError(f"http {resp.status_code}")
        err.response = resp
        raise err
    return resp.json()


def test_databricks_fake_sdk_bearer_to_gate_decision(databricks_fake: Runtime) -> None:
    client = TestClient(app)
    cred = IngressCredential(AGENT, bearer=lambda: "fake-token")
    gate = HttpGate("http://testserver", credential=cred, signed_transport=to_testclient(client))
    allowed, blocked = _decisions(gate)
    assert allowed["allow"] is True
    assert blocked["rule_id"] == "SVC-07"

    stranger = IngressCredential(AGENT, bearer=lambda: "stolen-or-unknown")
    bad = HttpGate("http://testserver", credential=stranger, signed_transport=to_testclient(client))
    assert bad.check(AGENT, "1", "read_ticket", {})["rule_id"] == "GATE-AUTH"
    spoof = HttpGate("http://testserver", credential=cred, signed_transport=to_testclient(client))
    assert spoof.check("payments", "1", "get_balance", {})["rule_id"] == "GATE-AUTH"
    counts = rt_counts(databricks_fake)
    assert counts["ingress_rejected_invalid_token"] == 1
    assert counts["ingress_rejected_agent_mismatch"] == 1
    rows = [
        r
        for r in databricks_fake.adapters.tables.query("console_action", {})
        if r["permission"] == "ingress.auth"
    ]
    assert len(rows) == 2 and all(r["outcome"] == "denied" for r in rows)


def rt_counts(rt: Runtime) -> dict[str, int]:
    return rt.gateway.metrics.snapshot()["counts"]

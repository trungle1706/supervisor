"""Tool-argument digests are keyed (HMAC-SHA256), so low-entropy args cannot be brute-forced."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterator
from pathlib import Path

import pytest

from supervisor.adapters.factory import Adapters
from supervisor.config import load_settings
from supervisor.core.args_hmac import DEV_ARGS_HASH_KEY, args_hmac, args_text, key_id
from supervisor.gateway.engine import Gateway
from supervisor.gateway.policy import StorePolicyProvider
from supervisor.wiring import build_runtime
from supervisor_agents.common import tracing
from tests.gateway.conftest import MemoryEvidence

ARGS = {"account_id": "ACC-0000000001"}


def test_default_key_is_labelled_dev(gateway: Gateway, evidence: MemoryEvidence) -> None:
    r = gateway.check("payments", "1.0.0", "get_balance", ARGS, {})
    p = evidence.of_type("gate_decision")[-1]
    assert "args_sha256" not in p
    assert p["args_hmac_key_id"] == "dev"
    assert p["args_hmac"] == args_hmac(ARGS, DEV_ARGS_HASH_KEY)
    plain = hashlib.sha256(args_text(ARGS).encode("utf-8")).hexdigest()
    assert p["args_hmac"] != plain
    ev = gateway.tables.query("agent_event", {"event_id": r["decision_id"]})[0]
    assert ev["args_hash"] == p["args_hmac"]


@pytest.fixture
def keyed_gateway(adapters: Adapters, evidence: MemoryEvidence) -> Iterator[Gateway]:
    from supervisor.gateway.policy import deploy_policy, load_policy_dir
    from tests.gateway.conftest import POLICY_DIR

    deploy_policy(load_policy_dir(POLICY_DIR), adapters.state, adapters.clock)
    gw = Gateway(
        StorePolicyProvider(adapters.state, refresh_s=0),
        adapters.tables,
        adapters.state,
        evidence,
        adapters.clock,
        args_hash_key="bank-secret-key-1",
    )
    try:
        yield gw
    finally:
        gw.close()


def test_configured_key_changes_digest_and_key_id(
    keyed_gateway: Gateway, evidence: MemoryEvidence
) -> None:
    keyed_gateway.check("payments", "1.0.0", "get_balance", ARGS, {})
    p = evidence.of_type("gate_decision")[-1]
    assert p["args_hmac"] == args_hmac(ARGS, "bank-secret-key-1")
    assert p["args_hmac"] != args_hmac(ARGS, DEV_ARGS_HASH_KEY)
    assert p["args_hmac_key_id"] == key_id("bank-secret-key-1") != "dev"
    assert "bank-secret-key-1" not in json.dumps(p)


def test_settings_key_reaches_gateway_and_agent_exporter(tmp_path: Path) -> None:
    settings = load_settings(
        sql_backend="sqlite", data_dir=tmp_path / "data", args_hash_key="k-from-settings"
    )
    rt = build_runtime(settings)
    try:
        assert rt.gateway.args_key_id == key_id("k-from-settings")
        # the agents' span exporter uses the same key: one digest per args in one deployment
        assert tracing.args_hash(ARGS) == args_hmac(ARGS, "k-from-settings")
    finally:
        rt.close()
        tracing.set_args_hash_key(None)
    assert tracing.args_hash(ARGS) == args_hmac(ARGS, DEV_ARGS_HASH_KEY)

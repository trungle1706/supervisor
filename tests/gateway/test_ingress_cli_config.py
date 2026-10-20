"""WP20: CLI (issue / rotate / list), settings defaults, startup warning, SDK signing."""

from __future__ import annotations

import logging
import os
import stat
from pathlib import Path
from typing import Any

import pytest

from supervisor.adapters.auth.agent_creds import FileKeyStore
from supervisor.config import load_settings
from supervisor.gateway import ingress_auth
from supervisor.gateway.ingress_auth import main
from supervisor.gateway.ingress_sign import H_AGENT, H_SIGNATURE, IngressCredential
from supervisor.gateway.mcp_proxy import make_credential
from supervisor.gateway.sdk import HttpGate


def run(capsys: pytest.CaptureFixture[str], *argv: str) -> tuple[int, str]:
    rc = main(list(argv))
    out = capsys.readouterr().out
    assert out.isascii(), "CLI output must be ASCII"
    return rc, out


def secret_of(out: str) -> str:
    return out.split("secret (shown once): ")[1].split()[0]


def test_issue_then_rotate_then_list(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    f = tmp_path / "keys.yaml"
    rc, out = run(capsys, "issue", "payments", "--keys-file", str(f))
    assert rc == 0 and out.startswith("[OK]")
    first = secret_of(out)
    assert len(first) == 64
    if os.name == "posix":
        assert stat.S_IMODE(f.stat().st_mode) == 0o600
    rc, out = run(capsys, "issue", "payments", "--keys-file", str(f))
    assert rc == 1 and "[FAIL]" in out and "rotate" in out
    rc, out = run(capsys, "rotate", "payments", "--keys-file", str(f), "--overlap-hours", "2")
    assert rc == 0 and "previous key valid until" in out
    second = secret_of(out)
    assert second != first
    keys = FileKeyStore(f).keys_for("payments")
    assert [k.state for k in keys] == ["current", "previous"]
    assert [k.secret for k in keys] == [second, first]
    rc, out = run(capsys, "list", "--keys-file", str(f))
    assert rc == 0 and "payments" in out and first not in out and second not in out
    rc, out = run(capsys, "rotate", "ghost", "--keys-file", str(f))
    assert rc == 1 and "use issue" in out
    rc, out = run(capsys, "issue", "bad id!", "--keys-file", str(f))
    assert rc == 2


def test_issue_to_client_key_file_does_not_print_the_secret(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    f, out_file = tmp_path / "keys.yaml", tmp_path / "agent.key"
    args = ("issue", "payments", "--keys-file", str(f), "--out-key-file", str(out_file))
    rc, out = run(capsys, *args)
    assert rc == 0
    secret = out_file.read_text(encoding="utf-8").strip()
    assert secret not in out
    if os.name == "posix":
        assert stat.S_IMODE(out_file.stat().st_mode) == 0o600
    cred = IngressCredential("payments", secret)
    assert FileKeyStore(f).keys_for("payments")[0].secret == secret
    assert H_SIGNATURE in cred.headers_for("POST", "/gate/check", b"{}")


def test_env_store_cli_prints_instructions(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("INGRESS_KEY_STORE", "env")
    rc, out = run(capsys, "rotate", "payments")
    assert rc == 0 and "INGRESS_AGENT_KEY_PAYMENTS" in out and "_PREV" in out


# ------------------------------------------------------------------ settings


def test_defaults_are_off_and_kind_follows_the_mode() -> None:
    s = load_settings()
    assert s.ingress_auth_enabled is False
    assert s.ingress_replay_window_s == 300
    assert (s.effective_ingress_kind, s.effective_ingress_key_store) == ("hmac", "file")
    app = load_settings(supervisor_mode="databricks_app")
    assert app.effective_ingress_kind == "databricks_sp"  # databricks_app defaults to SP bearer
    assert app.effective_ingress_key_store == "env"
    assert (
        load_settings(
            supervisor_mode="databricks_app", ingress_credential_kind="both"
        ).effective_ingress_kind
        == "both"
    )
    assert s.ingress_keys_file is not None and s.ingress_keys_file.name == "agent_keys.yaml"


def test_startup_warns_when_off_outside_dev(caplog: pytest.LogCaptureFixture) -> None:
    for mode, warns in (("laptop", True), ("databricks_app", True), ("dev", False)):
        caplog.clear()
        with caplog.at_level(logging.WARNING, logger="supervisor.ingress"):
            ingress_auth.startup_check(load_settings(supervisor_mode=mode))
        got = [r for r in caplog.records if "INGRESS_AUTH_ENABLED=0" in r.getMessage()]
        assert bool(got) == warns, mode
        assert len(got) <= 1  # one line


def test_startup_is_quiet_when_on(caplog: pytest.LogCaptureFixture, tmp_path: Path) -> None:
    s = load_settings(ingress_auth_enabled=True, ingress_keys_file=tmp_path / "k.yaml")
    ingress_auth.set_guard(ingress_auth.build_guard(s))
    try:
        with caplog.at_level(logging.WARNING, logger="supervisor.ingress"):
            ingress_auth.startup_check(s)
    finally:
        ingress_auth.set_guard(None)
    assert not [r for r in caplog.records if "INGRESS_AUTH_ENABLED=0" in r.getMessage()]


# ------------------------------------------------------------------ SDK / MCP proxy


class Seen:
    def __init__(self, reply: Any = None, status: int | None = None) -> None:
        self.calls: list[tuple[str, bytes, dict[str, str]]] = []
        self.reply = reply or {"allow": True, "action": "allow", "rule_id": None, "reason": "ok"}
        self.status = status

    def __call__(self, url: str, body: bytes, headers: Any, timeout: float) -> Any:
        self.calls.append((url, body, dict(headers)))
        if self.status:
            err = RuntimeError("http error")
            err.response = type("R", (), {"status_code": self.status})()  # type: ignore[attr-defined]
            raise err
        return self.reply


def test_http_gate_signs_the_exact_bytes_and_path() -> None:
    seen = Seen()
    cred = IngressCredential("payments", "k" * 40)
    gate = HttpGate("http://gw.invalid/v1/", credential=cred, signed_transport=seen)
    d = gate.check("payments", "1", "read", {"a": 1})
    assert d["allow"] is True
    url, body, headers = seen.calls[0]
    assert url == "http://gw.invalid/v1/gate/check" and headers[H_AGENT] == "payments"
    from supervisor.gateway.ingress_sign import compute_signature

    expect = compute_signature(
        "k" * 40,
        "payments",
        headers["X-Supervisor-Timestamp"],
        headers["X-Supervisor-Nonce"],
        "POST",
        "/v1/gate/check",
        body,
    )
    assert headers[H_SIGNATURE] == expect


def test_http_gate_without_credential_is_unchanged() -> None:
    calls: list[Any] = []

    def transport(url: str, payload: dict[str, Any], timeout: float) -> Any:
        calls.append((url, payload))
        return {"allow": True, "action": "allow"}

    assert HttpGate("http://gw.invalid", transport=transport).check("a", "1", "t", {})["allow"]
    assert calls[0][0] == "http://gw.invalid/gate/check"


@pytest.mark.parametrize("status", [401, 403])
def test_auth_refusal_always_fails_closed_even_for_read_only(status: int) -> None:
    gate = HttpGate(
        "http://gw.invalid",
        credential=IngressCredential("a", "k" * 40),
        signed_transport=Seen(status=status),
        fail_modes={"read": "read_only"},
    )
    d = gate.check("a", "1", "read", {})
    assert d["allow"] is False and d["rule_id"] == "GATE-AUTH"


def test_in_process_gate_is_unaffected() -> None:
    from supervisor.gateway.sdk import InProcessGate

    class GW:
        def check(self, *a: Any, **k: Any) -> dict[str, Any]:
            return {"allow": True, "action": "allow"}

    assert InProcessGate(GW()).check("a", "1", "t", {})["allow"] is True


def test_mcp_proxy_credential_from_key_file_and_bearer_env(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    key = tmp_path / "agent.key"
    key.write_text("m" * 40 + "\n", encoding="utf-8")
    os.chmod(key, 0o600)
    cred = make_credential("payments", str(key), None)
    assert cred is not None and H_SIGNATURE in cred.headers_for("POST", "/gate/check", b"{}")
    monkeypatch.setenv("MY_TOKEN_VAR", "fake-bearer-for-test")
    bearer = make_credential("payments", None, "MY_TOKEN_VAR")
    assert bearer.headers_for("POST", "/gate/check", b"{}")["Authorization"].startswith("Bearer ")
    monkeypatch.delenv("SUPERVISOR_AGENT_KEY", raising=False)
    monkeypatch.delenv("SUPERVISOR_AGENT_KEY_FILE", raising=False)
    assert make_credential("payments", None, None) is None  # unsigned proxy, as before

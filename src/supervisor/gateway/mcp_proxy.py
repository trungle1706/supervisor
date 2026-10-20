"""Minimal MCP stdio proxy: every ``tools/call`` passes the supervisor gate first.

Transport: newline-delimited JSON-RPC 2.0 (MCP stdio). A denied call is NOT forwarded.
It gets a normal result with ``isError: true`` (MCP tool error form, so the model can
read the reason) and the decision in ``result._meta.supervisor``. All other methods
(initialize, tools/list, notifications, ping) pass through unchanged.

Run: python -m supervisor.gateway.mcp_proxy --agent-id X --agent-version V
     --gate-url http://127.0.0.1:8000 [--key-file PATH] -- <upstream command...>

Ingress auth (WP20): with ``--key-file`` (or env SUPERVISOR_AGENT_KEY_FILE / SUPERVISOR_AGENT_KEY)
every gate call is signed for the agent id; ``--bearer-token-env NAME`` sends the bearer token in
that environment variable instead (Databricks service principal). Without them: unsigned, as before.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from typing import Any, Protocol, TextIO

from supervisor.core.ports import GateHook

PARSE_ERROR = -32700
INVALID_REQUEST = -32600
INTERNAL_ERROR = -32603


class Upstream(Protocol):
    def request(self, message: dict[str, Any]) -> dict[str, Any] | None: ...

    def close(self) -> None: ...


def _env_on() -> bool:
    return os.environ.get("INLINE_REDACTION_ENABLED", "").strip().lower() in (
        "1",
        "true",
        "yes",
        "on",
    )


def _error(id_: Any, code: int, message: str) -> dict[str, Any]:
    return {"jsonrpc": "2.0", "id": id_, "error": {"code": code, "message": message}}


def deny_response(id_: Any, verdict: dict[str, Any]) -> dict[str, Any]:
    """The MCP tool-error result for a refused call (shared with the HTTP proxy, WP26)."""
    text = f"blocked by supervisor: {verdict.get('rule_id')}: {verdict.get('reason')}"
    return {
        "jsonrpc": "2.0",
        "id": id_,
        "result": {
            "isError": True,
            "content": [{"type": "text", "text": text}],
            "_meta": {
                "supervisor": {
                    "action": verdict.get("action"),
                    "rule_id": verdict.get("rule_id"),
                    "decision_id": verdict.get("decision_id"),
                    "allow": False,
                }
            },
        },
    }


# Methods that read data without being a tools/call. Each goes through the gate as the tool
# ``mcp.<method with dots>`` (for example ``mcp.resources.read``) with the params as arguments, so
# the policy must list it (class read_only) or the gate refuses it by its own rule (WP26 F13).
DATA_METHODS = ("resources/read", "resources/templates/list", "prompts/get", "completion/complete")


def data_tool_name(method: str) -> str:
    return "mcp." + method.replace("/", ".")


def clean_call_params(params: dict[str, Any]) -> dict[str, Any]:
    """tools/call params as forwarded: name, arguments and _meta.progressToken only. Any other
    key (a smuggled _meta field, an extension) is dropped, because the gate never saw it."""
    out: dict[str, Any] = {"name": params["name"]}
    if "arguments" in params:
        out["arguments"] = params["arguments"]
    meta = params.get("_meta")
    if isinstance(meta, dict) and isinstance(meta.get("progressToken"), (str, int)):
        out["_meta"] = {"progressToken": meta["progressToken"]}
    return out


class McpGateProxy:
    def __init__(
        self,
        gate: GateHook,
        agent_id: str,
        agent_version: str,
        upstream: Upstream,
        *,
        inline_redaction: bool | None = None,
    ) -> None:
        self._gate = gate
        # WP24b: forward the gate's masked ``transformed_args`` instead of the original arguments.
        # None -> INLINE_REDACTION_ENABLED in the environment. Off by default.
        self._inline = _env_on() if inline_redaction is None else inline_redaction
        if self._inline:
            from supervisor.gateway.sdk import warn_inline_once

            warn_inline_once()
        self._agent_id = agent_id
        self._agent_version = agent_version
        self._upstream = upstream

    def handle(self, message: Any) -> dict[str, Any] | None:
        if not isinstance(message, dict) or message.get("jsonrpc") != "2.0":
            return _error(None, INVALID_REQUEST, "invalid request")
        method = message.get("method")
        if method in DATA_METHODS:
            return self._gated_data_method(message)
        if method != "tools/call":
            return self._forward(message)
        id_ = message.get("id")
        params = message.get("params")
        if not isinstance(params, dict) or not isinstance(params.get("name"), str):
            return _error(id_, INVALID_REQUEST, "tools/call needs params.name")
        args = params.get("arguments")
        if args is None:
            args = {}
        if not isinstance(args, dict):
            return _error(id_, INVALID_REQUEST, "params.arguments must be an object")
        ctx = {"transport": "mcp", "jsonrpc_id": "" if id_ is None else str(id_)}
        try:
            verdict = dict(
                self._gate.check(
                    self._agent_id, self._agent_version, params["name"], args, context=ctx
                )
            )
        except Exception as exc:  # fail closed
            verdict = {
                "allow": False,
                "action": "block",
                "rule_id": "GATE-ERROR",
                "reason": f"gate failure: {type(exc).__name__}",
            }
        if verdict.get("allow") is True:
            params = clean_call_params(params)
            transformed = verdict.get("transformed_args")
            if self._inline and isinstance(transformed, dict):
                params["arguments"] = transformed
            return self._forward({**message, "params": params})
        if id_ is None:  # a notification cannot receive a response
            return None
        return deny_response(id_, verdict)

    def _gated_data_method(self, message: dict[str, Any]) -> dict[str, Any] | None:
        id_ = message.get("id")
        params = message.get("params")
        args = params if isinstance(params, dict) else {}
        ctx = {"transport": "mcp", "mcp_method": message["method"]}
        try:
            verdict = dict(
                self._gate.check(
                    self._agent_id,
                    self._agent_version,
                    data_tool_name(message["method"]),
                    args,
                    context=ctx,
                )
            )
        except Exception as exc:  # fail closed
            verdict = {
                "allow": False,
                "rule_id": "GATE-ERROR",
                "reason": f"gate failure: {type(exc).__name__}",
            }
        if verdict.get("allow") is True:
            return self._forward(message)
        if id_ is None:
            return None
        text = f"blocked by supervisor: {verdict.get('rule_id')}: {verdict.get('reason')}"
        err = _error(id_, -32000, text)
        err["error"]["data"] = {"rule_id": verdict.get("rule_id"), "allow": False}
        return err

    def _forward(self, message: dict[str, Any]) -> dict[str, Any] | None:
        try:
            return self._upstream.request(message)
        except Exception as exc:
            if "id" not in message:
                return None
            return _error(message["id"], INTERNAL_ERROR, f"upstream failure: {type(exc).__name__}")


def run_stdio(proxy: McpGateProxy, stdin: TextIO, stdout: TextIO) -> None:
    for raw in stdin:
        line = raw.strip()
        if not line:
            continue
        try:
            message = json.loads(line)
        except ValueError:
            response: dict[str, Any] | None = _error(None, PARSE_ERROR, "parse error")
        else:
            response = proxy.handle(message)
        if response is not None:
            stdout.write(json.dumps(response, ensure_ascii=True, separators=(",", ":")) + "\n")
            stdout.flush()


class StdioUpstream:
    """Upstream MCP server run as a child process (started through the sandbox)."""

    def __init__(self, argv: list[str], *, cwd: str | None = None, timeout_s: float = 30.0) -> None:
        from supervisor import sandbox

        self._timeout_s = timeout_s
        self._proc = sandbox.start_pipes(argv, cwd=cwd or os.getcwd())

    def request(self, message: dict[str, Any]) -> dict[str, Any] | None:
        self._proc.send_line(json.dumps(message, ensure_ascii=True, separators=(",", ":")))
        if "id" not in message:
            return None
        while True:
            line = self._proc.read_line(self._timeout_s)
            if line is None:
                return _error(message["id"], INTERNAL_ERROR, "upstream timeout or closed")
            try:
                reply = json.loads(line)
            except ValueError:
                continue
            if isinstance(reply, dict) and reply.get("id") == message["id"]:
                return reply

    def close(self) -> None:
        self._proc.stop()


def make_credential(agent_id: str, key_file: str | None, bearer_env: str | None) -> Any:
    """The proxy's ingress credential (WP20) or None for an unsigned proxy."""
    from supervisor.gateway.ingress_sign import (
        CredentialError,
        IngressCredential,
        credential_from_env,
    )

    if bearer_env:
        if not os.environ.get(bearer_env):
            raise CredentialError(f"environment variable {bearer_env} is empty")
        return IngressCredential(agent_id, bearer=lambda: os.environ.get(bearer_env, ""))
    return credential_from_env(agent_id, key_file)


def main(argv: list[str] | None = None) -> int:
    from supervisor.bootstrap import bootstrap

    bootstrap()
    args_in = list(sys.argv[1:] if argv is None else argv)
    if "--" not in args_in:
        sys.stderr.write(
            "[FAIL] usage: ... --agent-id X --agent-version V --gate-url URL -- <cmd>\n"
        )
        return 2
    cut = args_in.index("--")
    p = argparse.ArgumentParser(prog="supervisor.gateway.mcp_proxy")
    p.add_argument("--agent-id", required=True)
    p.add_argument("--agent-version", required=True)
    p.add_argument("--gate-url", default="http://127.0.0.1:8000")
    p.add_argument("--key-file", default=None, help="HMAC key file (first line = secret)")
    p.add_argument("--bearer-token-env", default=None, help="env var holding a bearer token")
    p.add_argument(
        "--inline-redaction",
        action="store_true",
        help="forward the gate's masked arguments (also INLINE_REDACTION_ENABLED=1)",
    )
    ns = p.parse_args(args_in[:cut])
    command = args_in[cut + 1 :]
    if not command:
        sys.stderr.write("[FAIL] no upstream command after --\n")
        return 2
    from supervisor.gateway.ingress_sign import CredentialError
    from supervisor.gateway.sdk import HttpGate

    try:
        credential = make_credential(ns.agent_id, ns.key_file, ns.bearer_token_env)
    except CredentialError as exc:
        sys.stderr.write(f"[FAIL] ingress credential: {exc}\n")
        return 2
    upstream = StdioUpstream(command)
    try:
        proxy = McpGateProxy(
            HttpGate(ns.gate_url, credential=credential),
            ns.agent_id,
            ns.agent_version,
            upstream,
            inline_redaction=True if ns.inline_redaction else None,
        )
        run_stdio(proxy, sys.stdin, sys.stdout)
    finally:
        upstream.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

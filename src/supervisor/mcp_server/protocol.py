"""JSON-RPC 2.0 layer of the MCP server (WP-G6): initialize, ping, tools/list, tools/call.

Streamable HTTP, POST only, one JSON answer per request (a batch gets an array). The error shape
is the one of the WP26 proxy (``gateway/mcp_proxy.error_response``). Rules enforced here and not
in a prompt:

* an app that is not approved gets ``initialize`` and ``ping`` only (error -32001 otherwise);
* a tool needs its scope in the app row (-32002) and, when it writes, the console permission a
  person would need for the same action, given the roles of the app (-32003);
* a write tool writes only with ``confirm: true``; without it the planned change comes back and
  nothing is written; with it, two ``console_action`` rows (``attempted`` before the change, the
  outcome after) carry the app as actor;
* errors are JSON-RPC errors, never a 500; a failing tool says its class name, not a trace.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from typing import Any

from supervisor import __version__
from supervisor.adapters.auth.audit import (
    AuditUnavailable,
    audit_active,
    snapshot_hash,
    write_action,
    write_attempt,
    write_outcome,
)
from supervisor.cases.service import PermissionDenied
from supervisor.core import rbac
from supervisor.core.errors import NotFoundError, SupervisorError
from supervisor.gateway.mcp_proxy import error_response
from supervisor.mcp_server import PROTOCOL_VERSIONS, SERVER_NAME
from supervisor.mcp_server.registry import (
    APP_NOT_APPROVED,
    AUDIT_UNAVAILABLE,
    INTERNAL_ERROR,
    INVALID_PARAMS,
    INVALID_REQUEST,
    METHOD_NOT_FOUND,
    NOT_FOUND,
    PERMISSION_DENIED,
    RESULT_TOO_LARGE,
    SCOPE_DENIED,
    Registry,
    RpcError,
    Tool,
    validate_args,
)

log = logging.getLogger("supervisor.mcp_server")

MAX_RESULT_CHARS = 1_000_000
INSTRUCTIONS = (
    "Supervisor governance server. The server decides and enforces the rules; you only "
    "prepare. Every write tool needs confirm: true and writes a draft; without confirm it "
    "returns the planned change and writes nothing: show it to the user and ask. Never classify "
    "a system, approve a stage, accept a risk, change a risk level, close an incident or turn a "
    "guardian off: those are decisions of people in the console, and the server has no tool for "
    "them. Ask for any missing field instead of guessing. Prefer the library tools over general "
    "knowledge for regulations, starter risks and controls. Offer one next step at a time and "
    "match the depth to the risk level. Results carry ids and masked text only; do not try to "
    "recover names. Your output is decision support, not a decision."
)


@dataclass
class Caller:
    """What a tool needs to know about the request."""

    ctx: Any  # ConsoleContext
    app: dict[str, Any]
    principal: Any  # AuthPrincipal
    scopes: frozenset[str]
    request_id: str
    approved: bool


def read_target(tool: Tool, args: dict[str, Any]) -> tuple[str | None, str | None]:
    """The (kind, id) a read tool looked at, from its arguments."""
    if tool.target:
        return tool.target(args)
    for key, kind in (("system_id", "system"), ("agent_id", "agent"), ("task_id", "task")):
        if args.get(key):
            return kind, str(args[key])[:128]
    if tool.name == "get_entity":
        return str(args.get("kind")), str(args.get("id"))[:128]
    if tool.name == "list_entities":
        return str(args.get("kind")), None
    return None, None


def _ok(id_: Any, result: dict[str, Any]) -> dict[str, Any]:
    return {"jsonrpc": "2.0", "id": id_, "result": result}


def _rpc(id_: Any, exc: RpcError) -> dict[str, Any]:
    return error_response(id_, exc.code, exc.message)


class McpServer:
    def __init__(self, registry: Registry) -> None:
        self.registry = registry

    # ------------------------------------------------------------------ entry
    def handle(self, message: Any, caller: Caller) -> dict[str, Any] | None:
        """The answer to one JSON-RPC message; None for a notification."""
        if not isinstance(message, dict) or message.get("jsonrpc") != "2.0":
            return error_response(None, INVALID_REQUEST, "not a JSON-RPC 2.0 request")
        method = message.get("method")
        id_ = message.get("id")
        if not isinstance(method, str):
            return error_response(id_, INVALID_REQUEST, "method must be a string")
        if "id" not in message:  # a notification (notifications/initialized, cancelled, ...)
            return None
        if isinstance(id_, bool) or not isinstance(id_, str | int):
            return error_response(None, INVALID_REQUEST, "id must be a string or a number")
        params = message.get("params")
        if params is not None and not isinstance(params, dict):
            return error_response(id_, INVALID_PARAMS, "params must be an object")
        try:
            return _ok(id_, self._dispatch(method, params or {}, caller))
        except RpcError as exc:
            return _rpc(id_, exc)
        except Exception as exc:  # noqa: BLE001 - never a 500 and never a trace to the caller
            log.error("mcp request failed: %s", type(exc).__name__, exc_info=exc)
            return error_response(id_, INTERNAL_ERROR, f"server error: {type(exc).__name__}")

    def _dispatch(self, method: str, params: dict[str, Any], caller: Caller) -> dict[str, Any]:
        if method == "initialize":
            return self._initialize(params)
        if method == "ping":
            return {}
        if method not in ("tools/list", "tools/call"):
            raise RpcError(METHOD_NOT_FOUND, f"method {method} is not supported")
        if not caller.approved:
            raise RpcError(
                APP_NOT_APPROVED,
                f"app {caller.app['app_id']} is {caller.app['status']}; an admin approves it "
                "before it can list or call tools",
            )
        if method == "tools/list":
            return {
                "tools": [t.listing() for t in self.registry if t.scope in caller.scopes],
            }
        return self._call(params, caller)

    @staticmethod
    def _initialize(params: dict[str, Any]) -> dict[str, Any]:
        wanted = params.get("protocolVersion")
        version = wanted if wanted in PROTOCOL_VERSIONS else PROTOCOL_VERSIONS[0]
        return {
            "protocolVersion": version,
            "capabilities": {"tools": {"listChanged": False}},
            "serverInfo": {"name": SERVER_NAME, "version": __version__},
            "instructions": INSTRUCTIONS,
        }

    # ------------------------------------------------------------------ tools/call
    def _call(self, params: dict[str, Any], caller: Caller) -> dict[str, Any]:
        name = params.get("name")
        if not isinstance(name, str):
            raise RpcError(INVALID_PARAMS, "name must be a string")
        tool = self.registry.get(name)
        if tool is None:
            raise RpcError(INVALID_PARAMS, f"unknown tool {name[:64]!r}")
        if tool.scope not in caller.scopes:
            self._audit_denied(tool, caller, "scope_not_granted")
            raise RpcError(SCOPE_DENIED, f"this app has no {tool.scope} scope")
        if tool.permission and not rbac.allowed(caller.principal.roles, tool.permission):
            self._audit_denied(tool, caller, "permission_denied")
            raise RpcError(
                PERMISSION_DENIED,
                f"the roles of this app ({', '.join(sorted(caller.principal.roles))}) cannot "
                f"{rbac.PERMISSIONS[tool.permission][1].lower()}",
            )
        args = validate_args(tool.schema, params.get("arguments"), write=tool.write)
        confirm = bool(args.pop("confirm", False))
        try:
            if tool.write and confirm:
                result = self._write(tool, caller, args)
            else:
                result = tool.handler(caller, args, False)
                if tool.write:
                    result = {"written": False, "confirm_required": True, "planned_change": result}
                else:
                    self._audit_read(tool, caller, args)
        except RpcError:
            raise
        except AuditUnavailable as exc:
            raise RpcError(AUDIT_UNAVAILABLE, str(exc)) from None
        except PermissionDenied as exc:
            raise RpcError(PERMISSION_DENIED, str(exc)) from None
        except NotFoundError as exc:
            raise RpcError(NOT_FOUND, str(exc)) from None
        except SupervisorError as exc:
            raise RpcError(INVALID_PARAMS, str(exc)) from None
        text = json.dumps(result, ensure_ascii=False, sort_keys=True, default=str)
        if len(text) > MAX_RESULT_CHARS:
            raise RpcError(RESULT_TOO_LARGE, "the result is too large; ask for fewer rows")
        return {
            "content": [{"type": "text", "text": text}],
            "structuredContent": json.loads(text),
            "isError": False,
        }

    # ------------------------------------------------------------------ audit
    def _common(self, tool: Tool, caller: Caller) -> dict[str, Any]:
        return {
            "request_id": caller.request_id,
            "actor": caller.principal,
            "permission": tool.permission or "mcp.write",
            "method": "MCP",
            "path": f"/mcp/tools/{tool.name}",
        }

    def _audit_read(self, tool: Tool, caller: Caller, args: dict[str, Any]) -> None:
        """One ``ok`` row for each read that was answered: the tool name (in the path) and the
        id read (review M7). The read is already done, so a store failure is logged and the
        answer still goes out; a write never works that way."""
        if not audit_active(caller.ctx.settings):
            return
        kind, tid = read_target(tool, args)
        common = self._common(tool, caller)
        common["permission"] = "mcp.read"
        try:
            write_action(
                caller.ctx.tables,
                caller.ctx.clock,
                outcome="ok",
                target_kind=kind,
                target_id=tid,
                **common,
            )
        except Exception as exc:  # noqa: BLE001
            log.error("mcp read audit write failed: %s", type(exc).__name__)

    def _audit_denied(self, tool: Tool, caller: Caller, detail: str) -> None:
        """A refused write leaves one ``denied`` row (no side effect, so no ``attempted``)."""
        if not tool.write or not audit_active(caller.ctx.settings):
            return
        try:
            write_action(
                caller.ctx.tables,
                caller.ctx.clock,
                outcome="denied",
                detail=detail,
                **self._common(tool, caller),
            )
        except Exception as exc:  # noqa: BLE001 - the refusal is the answer; the log has the rest
            log.error("mcp denied-row write failed: %s", type(exc).__name__)

    def _write(self, tool: Tool, caller: Caller, args: dict[str, Any]) -> dict[str, Any]:
        """Run a confirmed write between the two audit rows."""
        ctx = caller.ctx
        if not audit_active(ctx.settings):
            return {"written": True, **tool.handler(caller, args, True)}
        kind, tid = tool.target(args) if tool.target else (None, None)
        common = self._common(tool, caller)
        common["target_kind"], common["target_id"] = kind, tid
        before = snapshot_hash(ctx.state, kind, tid)
        write_attempt(ctx.tables, ctx.clock, before_hash=before, **common)  # no row, no action
        outcome, detail, out, error = "ok", None, {}, None
        try:
            out = tool.handler(caller, args, True)
        except Exception as exc:  # noqa: BLE001 - re-raised after the outcome row
            error = exc
            outcome = "denied" if isinstance(exc, PermissionDenied) else "error"
            detail = "permission_denied" if outcome == "denied" else type(exc).__name__
        if kind and tid is None and out.get(f"{kind}_id"):
            common["target_id"] = tid = str(out[f"{kind}_id"])
        warning = write_outcome(
            ctx.tables,
            ctx.clock,
            outcome=outcome,
            before_hash=before,
            after_hash=snapshot_hash(ctx.state, kind, tid),
            detail=detail,
            **common,
        )
        if error is not None:
            raise error
        res: dict[str, Any] = {"written": True, **out}
        if warning:
            res["warning"] = warning
        return res

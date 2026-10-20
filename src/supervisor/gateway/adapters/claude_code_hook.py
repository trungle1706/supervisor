"""``PreToolUse`` hook for a developer's coding assistant: ask the gate, exit 2 to refuse (WP38).

The assistant starts this script before each tool call and passes one JSON object on stdin
(``session_id``, ``hook_event_name``, ``tool_name``, ``tool_input``). Exit code 0 lets the call
run; exit code 2 refuses it and the text on stderr is shown to the assistant. This is the public
hook contract of Claude Code; nothing from that product is imported or needed.

    python -m supervisor.gateway.adapters.claude_code_hook < event.json

Settings come from the environment (no secret on the command line, none printed):

========================  ===========================================================
SUPERVISOR_URL            base URL of Supervisor, required
SUPERVISOR_AGENT_ID       the agent (collector) id, required
SUPERVISOR_AGENT_VERSION  default ``1``
SUPERVISOR_AGENT_KEY      or SUPERVISOR_AGENT_KEY_FILE: the WP20 secret of that agent
SUPERVISOR_CONSUMER_ID    who is using it (default: the OS user name, cleaned)
SUPERVISOR_TIMEOUT_S      default 2
SUPERVISOR_FAIL_MODE      ``closed`` (default) or ``open``
SUPERVISOR_CLOSED_TOOLS   comma list of tool names that stay closed even when the mode is open
========================  ===========================================================

Closed by default: a missing setting, an unreadable event, an unreachable gate, a refused
credential, all end with exit code 2. ``open`` lets the call run when the gate is unreachable,
and nothing else. When the gate answers with masked arguments the hook prints the updated input
as the assistant's ``updatedInput`` answer (for versions that support it) and exits 0.
Output is ASCII.
"""

from __future__ import annotations

import getpass
import json
import os
import sys
from collections.abc import Mapping
from typing import Any, TextIO

from supervisor.core.ports import GateHook
from supervisor.gateway.adapters.common import GateClient, clean_id

EXIT_OK = 0
EXIT_REFUSE = 2
MAX_EVENT_BYTES = 1024 * 1024


def _ascii(text: str) -> str:
    """One printable ASCII line: no newline, no control or escape character from a gate answer."""
    return "".join(c if 32 <= ord(c) < 127 else "?" for c in text)


def _consumer(env: Mapping[str, str]) -> str | None:
    value = clean_id(env.get("SUPERVISOR_CONSUMER_ID"))
    if value:
        return value
    try:
        return clean_id(getpass.getuser())
    except Exception:  # noqa: BLE001 - no user name: no consumer id
        return None


def build_gate(env: Mapping[str, str]) -> GateHook | None:
    """HttpGate from the environment, or None when SUPERVISOR_URL or the agent id is missing."""
    url, agent = env.get("SUPERVISOR_URL", ""), env.get("SUPERVISOR_AGENT_ID", "")
    if not url or not agent:
        return None
    from supervisor.gateway.ingress_sign import credential_from_env
    from supervisor.gateway.sdk import HttpGate

    try:
        timeout = float(env.get("SUPERVISOR_TIMEOUT_S", "2"))
    except ValueError:
        timeout = 2.0
    return HttpGate(
        url, timeout_s=max(0.1, min(timeout, 30.0)), credential=credential_from_env(agent)
    )


def run(
    stdin_text: str,
    env: Mapping[str, str],
    gate: GateHook | None = None,
    out: TextIO | None = None,
    err: TextIO | None = None,
) -> int:
    """Decide for one event. Returns the exit code. ``gate`` is for tests."""
    out = out or sys.stdout
    err = err or sys.stderr

    def refuse(message: str) -> int:
        err.write(_ascii(f"[BLOCK] supervisor: {message}") + "\n")
        return EXIT_REFUSE

    mode = env.get("SUPERVISOR_FAIL_MODE", "closed")
    if mode not in ("closed", "open"):
        return refuse("SUPERVISOR_FAIL_MODE must be closed or open")
    if len(stdin_text.encode("utf-8", "replace")) > MAX_EVENT_BYTES:
        return refuse("event too large to inspect")
    try:
        event = json.loads(stdin_text)
    except ValueError:
        return refuse("event is not valid JSON")
    if not isinstance(event, dict):
        return refuse("event is not a JSON object")
    if event.get("hook_event_name", "PreToolUse") != "PreToolUse":
        return EXIT_OK  # this script only guards tool calls
    agent = env.get("SUPERVISOR_AGENT_ID", "")
    if gate is None:
        try:
            gate = build_gate(env)
        except Exception as exc:  # noqa: BLE001 - credential problems: class name only
            return refuse(f"credential problem ({type(exc).__name__})")
    if gate is None:
        return refuse("SUPERVISOR_URL and SUPERVISOR_AGENT_ID are not set")
    tool = event.get("tool_name")
    tool_input = event.get("tool_input")
    if not isinstance(tool, str) or not isinstance(tool_input, dict):
        return refuse("event has no tool_name or tool_input")
    try:
        client = GateClient(
            gate,
            agent,
            env.get("SUPERVISOR_AGENT_VERSION", "1"),
            fail_mode=mode,
            risk_classes={
                t.strip(): "money"
                for t in env.get("SUPERVISOR_CLOSED_TOOLS", "").split(",")
                if t.strip()
            },
            protocol="mcp" if tool.startswith("mcp__") else "llm",
        )
    except ValueError as exc:
        return refuse(str(exc))
    ans = client.check(
        tool, tool_input, consumer_id=_consumer(env), session_id=event.get("session_id")
    )
    if (stop := GateClient.refusal(ans)) is not None:
        verb = "paused" if stop.paused else "blocked"
        return refuse(
            f"{verb} by {stop.rule_id or 'policy'}: {stop.reason[:200]} "
            f"(reference {stop.correlation_id})"
        )
    new = ans.transformed_args
    if ans.status == "transform" and new is not None:
        out.write(
            json.dumps(
                {
                    "hookSpecificOutput": {
                        "hookEventName": "PreToolUse",
                        "permissionDecision": "allow",
                        "updatedInput": new,
                    }
                },
                ensure_ascii=True,
            )
            + "\n"
        )
    return EXIT_OK


def main(argv: list[str] | None = None) -> int:
    if argv is None:
        argv = sys.argv[1:]
    if argv and argv[0] in ("-h", "--help"):
        sys.stdout.write((__doc__ or "").split("\n\n", 1)[0] + "\n")
        sys.stdout.write("See docs/collectors.md. Reads one JSON event on stdin.\n")
        return 0
    data: Any = sys.stdin.read(MAX_EVENT_BYTES + 1)
    return run(data, os.environ)


if __name__ == "__main__":
    sys.exit(main())

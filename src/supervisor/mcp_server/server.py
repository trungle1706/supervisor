"""The registry of all tool groups and the process-wide server object (WP-G6)."""

from __future__ import annotations

import functools

from supervisor.mcp_server import tools_governance, tools_library, tools_supervisor
from supervisor.mcp_server.protocol import McpServer
from supervisor.mcp_server.registry import Registry


def build_registry() -> Registry:
    """Governance, library and supervisor tools. A refused name raises at this point."""
    reg = Registry()
    tools_governance.register(reg)
    tools_library.register(reg)
    tools_supervisor.register(reg)
    return reg


@functools.cache
def get_server() -> McpServer:
    return McpServer(build_registry())

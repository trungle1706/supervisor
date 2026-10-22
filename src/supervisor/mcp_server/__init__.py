"""MCP server (WP-G6, docs/mcp-server.md): pipelines and AI assistants work through the platform
the way people do in the console, with the same rules enforced in the server.

Off unless ``MCP_SERVER_ENABLED=1``. Entry points: ``python -m supervisor.mcp_server`` and the
router mounted by ``app.py`` at ``/mcp``. Standard library plus the packages already in use; the
JSON-RPC error shape is the one of the WP26 proxy (``gateway/mcp_proxy.py``).
"""

from __future__ import annotations

SCOPES: tuple[str, ...] = ("governance.read", "governance.write", "library.read", "supervisor.read")
PROTOCOL_VERSIONS: tuple[str, ...] = ("2025-06-18", "2025-03-26", "2024-11-05")
SERVER_NAME = "supervisor-mcp"

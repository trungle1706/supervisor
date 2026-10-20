"""Error types shared by core, adapters and the web layer."""

from __future__ import annotations


class SupervisorError(Exception):
    """Base error. The web layer turns it into HTTP 400 with the message."""


class ConfigError(SupervisorError):
    """Settings are missing or invalid."""


class SandboxError(SupervisorError):
    """A child process could not run."""


class SqlError(SupervisorError):
    """A SQL statement failed. The message names backend, target and fix."""


class ConcurrencyError(SqlError):
    """Optimistic concurrency check failed: the row changed since it was read."""


class NotFoundError(SupervisorError):
    """A requested row does not exist."""


class DuplicateKeyError(SqlError):
    """A row with the same primary key already exists."""


class AppendOnlyError(SqlError):
    """An UPDATE or DELETE hit an append-only table."""


class ReservedAgentIdError(SupervisorError):
    """The agent id is reserved by the product (HTTP 400)."""


RESERVED_AGENT_IDS = ("inventory",)  # the evidence lane of shadow-AI cases (WP24)
RESERVED_AGENT_PREFIXES = ("app:",)  # inventory node names of Databricks Apps (WP24)


def check_agent_id(agent_id: str) -> str:
    """Refuse ids the inventory uses for its own purposes; return the id unchanged."""
    low = agent_id.strip().lower()
    if low in RESERVED_AGENT_IDS or low.startswith(RESERVED_AGENT_PREFIXES):
        raise ReservedAgentIdError(
            f"agent id {agent_id!r} is reserved (ids 'inventory' and 'app:...' are used by the "
            "inventory); rename the agent folder or set a different id in its manifest"
        )
    return agent_id

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

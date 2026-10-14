"""Typed errors raised by ChatModel adapters. Messages never contain the API key."""

from __future__ import annotations

from supervisor.core.errors import SupervisorError


class LLMError(SupervisorError):
    """The model call failed (HTTP error, bad response, invalid JSON after retry)."""


class TruncatedError(LLMError):
    """The reply was cut off (``finish_reason == "length"``). Not retried blindly."""


class LLMTimeoutError(LLMError):
    """The model did not answer within the configured timeout."""


class LLMOutputError(LLMError):
    """The reply was not valid JSON for the requested schema, also after one retry."""

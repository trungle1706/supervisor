"""Registry of the tools the agent can call. Filled at import time."""
from typing import Callable

TOOL_REGISTRY: dict[str, Callable] = {}


def register_tool(name: str):
    """Decorator: put the function in TOOL_REGISTRY under the given name."""

    def wrap(fn: Callable) -> Callable:
        TOOL_REGISTRY[name] = fn
        return fn

    return wrap

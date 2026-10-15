"""Collect all tools into one dict at import time."""
import importlib

import yaml

import profile_tools  # noqa: F401  (the import fills TOOL_REGISTRY)
from actions import HANDLERS
from registry import TOOL_REGISTRY


def load_plugin_tools(path: str = "tools.yaml") -> dict:
    with open(path, encoding="utf-8") as fh:
        spec = yaml.safe_load(fh)
    module = importlib.import_module(spec["plugin_module"])
    return {name: getattr(module, name) for name in spec["enabled_tools"]}


ALL_TOOLS = {**TOOL_REGISTRY, **HANDLERS, **load_plugin_tools()}

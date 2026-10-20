"""Test wrapper: the synthetic rows come from supervisor.demo.activity_seed."""

from __future__ import annotations

from typing import Any

from supervisor.demo import activity_seed


def add_decision(c: Any, **kw: Any) -> str:
    return activity_seed.add_decision(c.ctx, **kw)

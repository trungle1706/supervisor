"""Tier 1: cheap monitor on 100 % of traces (async). Screens and escalates; never acts."""

from __future__ import annotations

from supervisor.judge.runner import JudgeCall, TierJudge


class Tier1Judge(TierJudge):
    """Tier 1 monitor. Uses the Tier 1 prompt (short screen) and the Tier 1 model."""

    tier = 1


__all__ = ["JudgeCall", "Tier1Judge"]

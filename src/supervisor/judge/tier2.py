"""Tier 2: strong judge on Tier 1 flags plus a random sample.

It reads the same masked transcript as Tier 1 but not Tier 1's score (independent
opinion: no anchoring). Disagreement between the tiers is handled by the protocol in
``service.py`` (defer to trusted)."""

from __future__ import annotations

from supervisor.judge.runner import JudgeCall, TierJudge


class Tier2Judge(TierJudge):
    """Tier 2 judge. Uses the Tier 2 prompt (scoring anchors) and the Tier 2 model."""

    tier = 2


__all__ = ["JudgeCall", "Tier2Judge"]

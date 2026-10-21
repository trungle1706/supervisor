"""``judge_advisory``: the existing Tier 1 judge as a report-only detector (WP37).

R1 holds: the finding says ``report`` and nothing in the gate reads its score to block or pause.
Without a real judge model the detector uses the deterministic MockJudge, and every finding it
produces is labelled ``mock`` (``Finding.is_mock``). A judge that cannot answer is a
``not_executed`` entry (``execution_failed``), never a pass and never a block (the detector is
configured ``fail_closed: false``).

The judge sees the MASKED call only (``judge/prompts/build.py`` masks every field first).
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from typing import Any

from supervisor.core.detectors import (
    Finding,
    SettingField,
    SettingsSchema,
    detector_id,
    not_executed,
    threshold_for,
)
from supervisor.core.ports import Masker
from supervisor.judge.runner import JudgeCall, TierJudge

# Frozen with the version string. Same scale as JUDGE_T1_THRESHOLD_BP (5000 = escalate).
PRESETS: dict[str, int] = {"strict": 3_000, "balanced": 5_000, "lenient": 7_000}


def mock_tier1(masker: Masker) -> TierJudge:
    """A Tier 1 judge on the deterministic mock model (offline, labelled mock)."""
    from supervisor.judge.mockjudge import MockJudgeChat
    from supervisor.judge.router import JudgeModel
    from supervisor.judge.tier1 import Tier1Judge

    model = JudgeModel(1, "primary", MockJudgeChat(1, model_id="mock-judge-t1"), "local")
    return Tier1Judge(model, masker, timeout_s=5.0, max_retries=0)


def _dump(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, default=str)


class JudgeAdvisoryDetector:
    slug = "judge_advisory"
    name = "Judge opinion (advisory)"
    category = "advisory"
    version = "1.0.0"
    sides = ("input", "output")
    protocols = ("all",)
    presets = PRESETS
    settings_schema = SettingsSchema(
        (
            SettingField(
                "min_chars",
                "Skip payloads shorter than (characters)",
                "integer",
                default=0,
                minimum=0,
                maximum=100_000,
            ),
        )
    )

    def __init__(self, masker: Masker, judge: TierJudge | None = None) -> None:
        self.masker = masker
        self.judge = judge or mock_tier1(masker)

    def evaluate(
        self, payload: Mapping[str, Any], settings: Mapping[str, Any], direction: str
    ) -> list[Finding]:
        did = detector_id(self)
        threshold = threshold_for(self, settings)
        preset = str(settings.get("preset") or "balanced")
        meta = payload.get("meta") or {}
        if direction == "input":
            args = payload.get("args")
            result = payload.get("tool_results")
        else:
            args, result = None, payload.get("output")
        text_len = len(_dump(args)) + len(_dump(result))
        if text_len < int(settings.get("min_chars") or 0):
            return []
        event = {
            "event_type": "tool_call",
            "agent_id": meta.get("agent_id") or "unknown",
            "tool_name": meta.get("tool_name"),
            "args_masked": _dump(args) if args is not None else None,
            "result_masked": _dump(result) if result is not None else None,
        }
        call: JudgeCall = self.judge.judge(
            [event], agent_id=str(event["agent_id"]), agent_version=meta.get("agent_version")
        )
        if call.status == "unavailable" or call.suspicion_bp is None:
            return [not_executed(self.slug, did, "execution_failed", call.status, preset)]
        if call.label == "benign" and call.suspicion_bp < threshold:
            return []
        return [
            Finding(
                detector_slug=self.slug,
                detector_id=did,
                code=f"judge.{call.label}",
                score_bp=int(call.suspicion_bp),
                threshold_bp=threshold,
                action_hint="report",
                preset=preset,
                is_mock=bool(call.is_mock),
            )
        ]

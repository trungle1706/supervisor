"""``judge_moderation``: toxicity and topic scope by the judge model, report only (WP-D4).

Two kinds of question, each with its own prompt (``judge/moderation.py``):

* ``toxicity``: one yes or no answer with a score. Finding ``moderation.toxic``.
* ``topics``: up to five ``{name, definition}`` entries. Each topic is scored on its own and the
  definition is what is scored (the name is only the label). Finding
  ``moderation.topic:<name>``.

On the input side the text is the user text in ``args`` (the latest user message when ``args``
holds a message list); on the output side it is the assistant text in ``output``. Long text is
read up to 10 000 characters, in overlapping windows; the highest window score per question wins.

Rules the code keeps:

* R1. Every finding says ``report``. Nothing in the gate reads these scores to block or pause,
  and the detector is advisory (never fails closed).
* The judge sees the MASKED text only (masked once, before the windows are cut).
* Without a real judge model the MockModerationChat answers and every finding says
  ``mock: true``. A judge that cannot answer is a ``not_executed`` entry, never a pass.
* The judge model family rule is checked where the judge is built (``JudgeRouter``); this
  detector takes the judge the product already built for ``judge_advisory``.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from supervisor.core.detectors import (
    Finding,
    SettingField,
    SettingsSchema,
    detector_id,
    not_executed,
    threshold_for,
    walk_leaves,
)
from supervisor.core.ports import Masker
from supervisor.detectors.judge_advisory import PRESETS, mock_tier1
from supervisor.judge.moderation import MAX_TEXT_CHARS, Answer, ModerationJudge
from supervisor.judge.runner import TierJudge

MAX_TOPICS = 5
MAX_NAME_CHARS = 120
MAX_DEFINITION_CHARS = 400
TOPIC_KEYS = ("name", "definition")


def topic_problems(topics: Any) -> list[str]:
    """Checks the declarative schema cannot express: the shape of each topic entry."""
    if topics is None:
        return []
    if not isinstance(topics, list):
        return ["topics: expected a list"]
    out: list[str] = []
    if len(topics) > MAX_TOPICS:
        out.append(f"topics: more than {MAX_TOPICS} topics")
    seen: set[str] = set()
    for i, t in enumerate(topics):
        where = f"topics[{i}]"
        if not isinstance(t, Mapping):
            out.append(f"{where}: expected an object with name and definition")
            continue
        extra = sorted(str(k) for k in t if k not in TOPIC_KEYS)
        if extra:
            out.append(f"{where}: unknown key {extra[0]}")
        name, definition = t.get("name"), t.get("definition")
        if not isinstance(name, str) or not name.strip():
            out.append(f"{where}.name: required text")
        elif len(name) > MAX_NAME_CHARS:
            out.append(f"{where}.name: longer than {MAX_NAME_CHARS} characters")
        elif any(ord(c) < 32 for c in name):
            out.append(f"{where}.name: control characters")
        elif name in seen:
            out.append(f"{where}.name: duplicate")
        else:
            seen.add(name)
        if not isinstance(definition, str) or not definition.strip():
            out.append(f"{where}.definition: required text")
        elif len(definition) > MAX_DEFINITION_CHARS:
            out.append(f"{where}.definition: longer than {MAX_DEFINITION_CHARS} characters")
    return out


def extract_text(part: str, value: Any) -> str:
    """The text to read: the latest user message of a message list, else every string leaf."""
    if isinstance(value, Mapping):
        msgs = value.get("messages")
        if isinstance(msgs, list):
            for m in reversed(msgs):
                if isinstance(m, Mapping) and m.get("role") == "user":
                    c = m.get("content")
                    if isinstance(c, str):
                        return c[:MAX_TEXT_CHARS]
    parts: list[str] = []
    size = 0
    for leaf in walk_leaves(part, value):
        parts.append(leaf.text)
        size += len(leaf.text) + 1
        if size >= MAX_TEXT_CHARS:
            break
    return "\n".join(parts)[:MAX_TEXT_CHARS]


class JudgeModerationDetector:
    slug = "judge_moderation"
    name = "Moderation: toxicity and topics (judge, advisory)"
    category = "advisory"
    version = "1.0.0"
    sides = ("input", "output")
    protocols = ("all",)
    presets = PRESETS
    settings_schema = SettingsSchema(
        (
            SettingField(
                "toxicity",
                "Toxicity question",
                "object",
                default={"enabled": False},
                fields=(
                    SettingField(
                        "enabled",
                        "Ask whether the text is toxic",
                        "boolean",
                        default=False,
                    ),
                ),
            ),
            SettingField(
                "topics",
                "Topics (name and definition; up to 5)",
                "array",
                items="object",
                default=[],
                max_length=MAX_TOPICS,
                description=(
                    "Each topic is scored on its own. The definition (up to 400 characters) is "
                    "what is scored; the name is only the label of the finding."
                ),
            ),
        )
    )

    def __init__(self, masker: Masker, judge: TierJudge | None = None) -> None:
        tier = judge or mock_tier1(masker)
        self.masker = masker
        self.mod = ModerationJudge(
            tier.model,
            masker,
            timeout_s=tier.timeout_s,
            max_retries=tier.max_retries,
        )

    def evaluate(
        self, payload: Mapping[str, Any], settings: Mapping[str, Any], direction: str
    ) -> list[Finding]:
        did = detector_id(self)
        preset = str(settings.get("preset") or "balanced")
        tox = settings.get("toxicity")
        want_toxic = isinstance(tox, Mapping) and bool(tox.get("enabled"))
        topics = settings.get("topics") or []
        if topic_problems(topics):
            return [not_executed(self.slug, did, "invalid_config", "topics", preset)]
        if not want_toxic and not topics:
            return []  # nothing is asked: no judge call, no cost
        part = "args" if direction == "input" else "output"
        text = extract_text(part, payload.get(part))
        if not text.strip():
            return []
        threshold = threshold_for(self, settings)
        windows_ = self.mod.prepare(text)
        findings: list[Finding] = []
        failed = ""
        asked: list[tuple[str, Answer]] = []
        if want_toxic:
            asked.append(("moderation.toxic", self.mod.toxic(windows_)))
        for t in topics:
            asked.append(
                (f"moderation.topic:{t['name']}", self.mod.topic(t["definition"], windows_))
            )
        for code, ans in asked:
            if ans.score_bp is None:
                failed = failed or ans.status
                continue
            if ans.score_bp < threshold:
                continue
            findings.append(
                Finding(
                    detector_slug=self.slug,
                    detector_id=did,
                    code=code,
                    score_bp=ans.score_bp,
                    threshold_bp=threshold,
                    action_hint="report",
                    preset=preset,
                    is_mock=ans.is_mock,
                )
            )
        if failed:
            findings.append(not_executed(self.slug, did, "execution_failed", failed, preset))
        return findings

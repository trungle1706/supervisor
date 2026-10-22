"""``judge_moderation``: harmful language and subject scope, asked of the judge (WP-D4).

The detector puts up to six yes or no questions to the judge model about a text:

* ``toxicity``: is the text harmful language? Finding ``moderation.toxic``.
* ``topics``: up to five ``{name, definition}`` entries. The definition is the subject the text
  is compared with; the name is only the label of the finding ``moderation.topic:<name>``.

The input text is the user text in ``args`` (the latest user message when ``args`` holds a
message list); the output text is the ``output`` part. A long text is read up to 10 000
characters in overlapping windows, and the highest "yes" score of a question over the windows is
its score. All questions go in ONE prompt per window, so a check costs at most 10 model calls
(``max_calls`` caps it, default 12), usually 1 to 3, and it stops at a deadline.

Rules the code keeps:

* R1. Every finding says ``report``. Nothing in the gate reads these scores to block or pause,
  and the detector is advisory (never fails closed). A "no" answer never gives a finding.
* The judge sees the MASKED text only (masked once, before the windows are cut).
* Without a real judge model the MockModerationChat answers and every finding says
  ``mock: true``. A judge that cannot answer is a ``not_executed`` entry, never a pass; a
  question that was not asked because the deadline or call cap came first is
  ``not_executed`` with reason ``budget_exhausted``.
* The gate tells this detector its deadline (``_budget_ms``); the detector stops asking at 80
  percent of it, so its thread leaves the shared pool before the gate gives up on it.
* The judge model family rule is checked where the judge is built (``JudgeRouter``); this
  detector takes the judge the product already built for ``judge_advisory``.
"""

from __future__ import annotations

import time
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
from supervisor.judge.moderation import (
    MAX_CALLS,
    MAX_TEXT_CHARS,
    TOXIC_ID,
    ModerationJudge,
    Question,
)
from supervisor.judge.runner import TierJudge

MAX_TOPICS = 5
MAX_NAME_CHARS = 120
MAX_DEFINITION_CHARS = 400
TOPIC_KEYS = ("name", "definition")
DEADLINE_SHARE = 0.8  # of the gate's time for this detector
DEFAULT_BUDGET_MS = 500  # when the detector is called without a gate (the harness)


def _has_control(text: str) -> bool:
    return any(ord(c) < 32 or ord(c) == 127 for c in text)


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
        elif _has_control(name):
            out.append(f"{where}.name: control characters")
        elif name in seen:
            out.append(f"{where}.name: duplicate")
        else:
            seen.add(name)
        if not isinstance(definition, str) or not definition.strip():
            out.append(f"{where}.definition: required text")
        elif len(definition) > MAX_DEFINITION_CHARS:
            out.append(f"{where}.definition: longer than {MAX_DEFINITION_CHARS} characters")
        elif _has_control(definition):
            out.append(f"{where}.definition: control characters (write it as one line)")
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
    name = "Moderation: harmful language and subject scope (judge, advisory)"
    category = "advisory"
    version = "1.0.0"
    sides = ("input", "output")
    protocols = ("all",)
    presets = PRESETS
    budget_aware = True  # the registry passes `_budget_ms` (this detector's deadline)
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
                        "Ask whether the text is harmful language",
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
                    "Each topic is a subject the text is compared with. The definition (up to "
                    "400 characters, one line) is what the judge reads; the name is only the "
                    "label of the finding."
                ),
            ),
            SettingField(
                "max_calls",
                "Most model calls for one check",
                "integer",
                default=MAX_CALLS,
                minimum=1,
                maximum=30,
                description="One call per text window; retries count. Hard cap per check.",
            ),
            SettingField(
                "timeout_ms",
                "Time this detector may take (ms); empty = the gate's timeout",
                "integer",
                default=None,
                minimum=10,
                maximum=60_000,
                description=(
                    "Replaces limits.timeout_ms for this detector only. A real judge model "
                    "needs seconds, not the 500 ms of the gate."
                ),
            ),
        )
    )

    def __init__(self, masker: Masker, judge: TierJudge | None = None) -> None:
        # a judge object without a model (a test double of the trace judge) falls back to the mock
        model = getattr(judge, "model", None) or mock_tier1(masker).model
        self.masker = masker
        self.mod = ModerationJudge(
            model,
            masker,
            timeout_s=float(getattr(judge, "timeout_s", 30.0)),
            max_retries=int(getattr(judge, "max_retries", 0)),
        )

    def evaluate(
        self, payload: Mapping[str, Any], settings: Mapping[str, Any], direction: str
    ) -> list[Finding]:
        started = time.monotonic()
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
        budget_ms = int(settings.get("_budget_ms") or DEFAULT_BUDGET_MS)
        deadline = started + DEADLINE_SHARE * budget_ms / 1000
        questions: list[Question] = []
        codes: dict[str, str] = {}
        if want_toxic:
            questions.append(Question(TOXIC_ID))
            codes[TOXIC_ID] = "moderation.toxic"
        for i, t in enumerate(topics, 1):
            questions.append(Question(f"t{i}", t["definition"]))
            codes[f"t{i}"] = f"moderation.topic:{t['name']}"
        answers = self.mod.ask(
            questions,
            self.mod.prepare(text),
            deadline=deadline,
            max_calls=int(settings.get("max_calls") or MAX_CALLS),
        )
        findings: list[Finding] = []
        failed: list[str] = []
        for q in questions:
            ans = answers[q.qid]
            if ans.status not in ("ok", "no_text") and ans.status not in failed:
                failed.append(ans.status)
            if ans.score_bp and ans.score_bp >= threshold:  # only a "yes" has a score
                findings.append(
                    Finding(
                        detector_slug=self.slug,
                        detector_id=did,
                        code=codes[q.qid],
                        score_bp=ans.score_bp,
                        threshold_bp=threshold,
                        action_hint="report",
                        preset=preset,
                        is_mock=ans.is_mock,
                    )
                )
        for status in failed:
            reason = "budget_exhausted" if status == "budget_exhausted" else "execution_failed"
            findings.append(not_executed(self.slug, did, reason, status, preset))
        return findings

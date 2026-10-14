"""Quality scorers: groundedness + guideline via the ChatModel port (mocked), advisory only."""

from __future__ import annotations

import json
from typing import Any

import pytest

from supervisor.adapters.llm.mock import MockChat
from supervisor.adapters.masking.vn_regex import VnRegexMasker
from supervisor.judge.router import FamilyConflictError
from supervisor.monitors.quality import CHECKER_GROUNDED, CHECKER_GUIDELINE, QualityScorer
from tests.judge.conftest import MemoryTables, assert_no_floats
from tests.monitors.conftest import T0


def _ev(eid: str, tool: str, *, args: Any = None, result: str | None = None) -> dict[str, Any]:
    return {
        "event_id": eid,
        "trace_id": "tr-q",
        "agent_id": "customer_service",
        "event_type": "tool_call",
        "tool_name": tool,
        "args_masked": json.dumps(args) if args is not None else None,
        "result_masked": result,
        "ts": T0,
    }


TRACE = [
    _ev("e1", "read_ticket", args={"ticket_id": "TCK-1"}, result="fee 200.000 VND charged"),
    _ev(
        "e2",
        "reply",
        args={"ticket_id": "TCK-1", "text": "We refunded 200.000 VND. Call 0912345678."},
    ),
]


class SpyChat(MockChat):
    def __init__(self, response: Any, **kw: Any) -> None:
        super().__init__(model_id="mock-quality-v1", **kw)
        self.response = response
        self.seen: list[Any] = []

    def complete_json(self, messages, json_schema, timeout_s):  # noqa: ANN001, ANN201
        self.seen.append(messages)
        if isinstance(self.response, Exception):
            raise self.response
        return self.response


def test_scores_reply_writes_advisory_verdicts(clock, evidence) -> None:
    chat = SpyChat({"groundedness_bp": 3000, "guideline_bp": 9000, "issues": ["refund not shown"]})
    tables = MemoryTables()
    masker = VnRegexMasker(b"k", "t")
    q = QualityScorer(chat, clock, masker=masker, tables=tables, evidence=evidence, sample_bp=10000)
    results = q.sweep(TRACE)
    assert len(results) == 1
    r = results[0]
    assert (r.groundedness_bp, r.guideline_bp, r.error) == (3000, 9000, None)
    prompt = chat.seen[0][1]["content"]
    assert "fee 200.000 VND charged" in prompt and "0912345678" not in prompt  # masked
    rows = tables.tables["verdict"]
    assert {v["checker_id"] for v in rows} == {CHECKER_GROUNDED, CHECKER_GUIDELINE}
    for v in rows:
        assert v["advisory"] is True and v["action"] == "log" and v["tier"] == 1
        assert v["is_mock"] is True and "mock" in v["model_id"] and v["role"] == "quality"
    assert {v["label"] for v in rows} == {"low", "pass"}
    (payload,) = evidence.of_type("quality_score")
    assert_no_floats(payload)
    assert payload["groundedness_bp"] == 3000 and payload["advisory"] is True


def test_sampling_is_deterministic_and_off_at_zero(clock) -> None:
    q0 = QualityScorer(SpyChat({}), clock, sample_bp=0)
    assert q0.sweep(TRACE) == []
    q = QualityScorer(SpyChat({}), clock, sample_bp=5000)
    hits = [q.sampled(f"e{i}") for i in range(2000)]
    assert hits == [q.sampled(f"e{i}") for i in range(2000)]
    assert 800 < sum(hits) < 1200


def test_model_error_or_bad_output_is_recorded_not_raised(clock, evidence) -> None:
    q = QualityScorer(SpyChat(TimeoutError("slow")), clock, evidence=evidence, sample_bp=10000)
    (r,) = q.sweep(TRACE)
    assert r.error == "TimeoutError" and r.groundedness_bp is None
    q2 = QualityScorer(SpyChat({"groundedness_bp": 1.5, "guideline_bp": 99999, "issues": []}),
                       clock, sample_bp=10000)  # fmt: skip
    (r2,) = q2.sweep(TRACE)
    assert r2.error == "invalid_scores" and r2.groundedness_bp is None


def test_family_must_differ_from_agent(clock) -> None:
    with pytest.raises(FamilyConflictError):
        QualityScorer(
            SpyChat({}, family="qwen"), clock, agent_families={"customer_service": "qwen3"}
        )
    QualityScorer(SpyChat({}, family="llama"), clock, agent_families={"customer_service": "qwen"})

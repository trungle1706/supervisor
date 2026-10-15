from __future__ import annotations

import dataclasses

from supervisor.adapters.llm.mock import MockChat
from supervisor.advisory.compliance.narrative import build_narrative

from ._factory import tiny_matrix


class _Real:
    is_mock = False
    family = "real"
    model_id = "real-model-1"

    def __init__(self, text="One. Two. Three. Four. Five.", fail=False):
        self.text, self.fail, self.sent = text, fail, []

    def complete_json(self, messages, json_schema, timeout_s):
        self.sent.append(messages)
        if self.fail:
            raise RuntimeError("boom")
        return {"text": self.text}


def test_mock_is_labelled_and_deterministic():
    m = tiny_matrix()
    a = build_narrative(m, MockChat())
    b = build_narrative(m, MockChat())
    assert a == b
    assert a.is_mock is True and "mock" in a.model_id and a.label == "advisory"
    assert "Threshold gaps: 1" in a.text


def test_narrative_never_changes_statuses():
    m = tiny_matrix()
    before = [(r.obligation_id, r.status, r.applies) for r in m.rows]
    n = build_narrative(m, MockChat())
    m2 = dataclasses.replace(m, narrative=n)
    assert [(r.obligation_id, r.status, r.applies) for r in m2.rows] == before
    assert m2.summary == m.summary


def test_real_model_gets_summary_only():
    chat = _Real()
    n = build_narrative(tiny_matrix(), chat)
    assert n.text.startswith("One.") and n.is_mock is False and n.label == "advisory"
    sent = " ".join(msg["content"] for msg in chat.sent[0])
    assert "OB-1" not in sent and "Duty one" not in sent


def test_error_falls_back_to_template_still_labelled():
    n = build_narrative(tiny_matrix(), _Real(fail=True))
    assert "Decision 33 suggestion" in n.text
    assert n.label == "advisory" and n.model_id == "real-model-1"


def test_empty_text_falls_back():
    n = build_narrative(tiny_matrix(), _Real(text="  "))
    assert "Decision 33 suggestion" in n.text

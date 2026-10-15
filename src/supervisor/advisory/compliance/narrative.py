"""Short narrative for the matrix (WP14). Advisory. Mock by default.

The narrative never changes a row or a status. With a mock model (or any error) the text
comes from a fixed template over the summary. With a real model only the summary, the
Decision 33 lines and the threshold findings are sent: no repository text.

Not legal advice. Bank counsel must confirm.
"""

from __future__ import annotations

import json
from typing import Any

from supervisor.advisory.compliance.model import Narrative, ObligationMatrix
from supervisor.core.ports import ChatModel

_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {"text": {"type": "string"}},
    "required": ["text"],
    "additionalProperties": False,
}
_TIMEOUT_S = 60.0


def _facts(matrix: ObligationMatrix) -> dict[str, Any]:
    s = matrix.summary
    return {
        "product": matrix.header.product_name,
        "obligations": matrix.header.obligations,
        "by_status_applies_yes": s.get("by_status", {}),
        "by_applies": s.get("by_applies", {}),
        "open_questions": s.get("questions", 0),
        "threshold_gaps": s.get("threshold_gaps", 0),
        "decision33_class": matrix.decision33.classification,
        "decision33_lines": list(matrix.decision33.lines),
        "threshold_findings": [
            {"id": f.id, "verdict": f.verdict, "reason": f.reason}
            for f in matrix.thresholds
            if f.id.endswith("-effective")
        ],
    }


def template_text(matrix: ObligationMatrix) -> str:
    """Deterministic English summary built only from the matrix numbers."""
    s = matrix.summary
    by = s.get("by_status", {})
    ap = s.get("by_applies", {})
    sentences = [
        f"Product {matrix.header.product_name} was checked against "
        f"{matrix.header.obligations} obligations in the knowledge base.",
        f"{ap.get('yes', 0)} apply, {ap.get('needs_answer', 0)} need an answer and "
        f"{ap.get('no', 0)} do not apply.",
        f"Of the rows that apply: {by.get('met', 0)} met, {by.get('partial', 0)} partial, "
        f"{by.get('gap', 0)} gap, {by.get('bank_process', 0)} bank process.",
        f"Threshold gaps: {s.get('threshold_gaps', 0)}. Open questions: {s.get('questions', 0)}.",
        f"Decision 33 suggestion: {matrix.decision33.classification}. Bank counsel must confirm.",
    ]
    return " ".join(sentences)


def build_narrative(matrix: ObligationMatrix, chat: ChatModel) -> Narrative:
    """Advisory narrative; labelled; mock when the model is a mock. Never raises."""
    is_mock = bool(getattr(chat, "is_mock", False))
    model_id = str(getattr(chat, "model_id", "unknown"))
    if is_mock:
        return Narrative(text=template_text(matrix), model_id=model_id, is_mock=True)
    messages = [
        {
            "role": "system",
            "content": (
                "You summarise a compliance obligations matrix for a bank reader. "
                "Write exactly 5 plain sentences. Use only the facts given. Do not give "
                "legal advice. Do not change or restate any status as a decision."
            ),
        },
        {"role": "user", "content": json.dumps(_facts(matrix), sort_keys=True, ensure_ascii=False)},
    ]
    try:
        out = chat.complete_json(messages, _SCHEMA, _TIMEOUT_S)
        text = str(out["text"]).strip()
        if not text:
            raise ValueError("empty narrative")
    except Exception:  # advisory text only: any failure falls back to the template
        return Narrative(text=template_text(matrix), model_id=model_id, is_mock=False)
    return Narrative(text=text, model_id=model_id, is_mock=False)

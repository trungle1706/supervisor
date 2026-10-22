"""MockGuardModel: a deterministic stand-in for a guard model (WP-D3). Offline, no model.

It looks for a short list of attack phrases (English and Vietnamese, with or without diacritics)
and answers ``malicious`` with a score that grows with the number of phrases. It proves the
detector, the harness and the gate path; it says nothing about a real model, so ``is_mock`` is
true and every finding that comes from it is labelled ``mock``.
"""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Callable, Sequence

from supervisor.core.ports import GuardScore

_CUES = tuple(
    re.compile(p)
    for p in (
        r"ignore (all |any )?(the )?(previous|prior|above|earlier|your) (instructions|rules)",
        r"disregard (all |any )?(the )?(previous|prior|above|your)",
        r"forget (all |everything |your )?(previous |prior )?(instructions|rules)",
        r"you are now|developer mode|do anything now|\bdan\b|jailbreak|no restrictions",
        r"(reveal|print|show|repeat) (me )?(your |the )?(system|hidden) prompt",
        r"(note|message|instruction)s? (to|for) (the )?(ai|assistant|agent|model)",
        r"do not (tell|inform|mention)[a-z ]{0,20}(user|customer)",
        r"(send|transfer|wire|move) (all|everything|the whole)[a-z ]{0,30}(to|into)",
        r"bo qua (moi|tat ca|het)[a-z ]{0,12}(huong dan|quy tac|chi dan|lenh)",
        r"quen (het |moi )?(huong dan|quy tac|chi dan)",
        r"ban (bay )?gio la|che do (nha phat trien|khong gioi han)",
        r"(tiet lo|in ra|cho toi xem)[a-z ]{0,12}(prompt|chi dan he thong)",
        r"khong (duoc )?(noi|bao|thong bao)[a-z ]{0,12}(nguoi dung|khach hang)",
        r"(chuyen|chuyen khoan) (het|toan bo|tat ca)[a-z ]{0,20}(sang|den|vao)",
    )
)


def _fold(text: str) -> str:
    """Lower case, no diacritics (``đ`` becomes ``d``): one form for the cue list."""
    low = text.lower().replace("đ", "d")
    nfd = unicodedata.normalize("NFD", low)
    return "".join(c for c in nfd if unicodedata.category(c) != "Mn")


def mock_score(text: str) -> GuardScore:
    folded = _fold(text)
    hits = sum(1 for cue in _CUES if cue.search(folded))
    if hits == 0:
        return {"label": "benign", "score_bp": 0}
    return {"label": "malicious", "score_bp": min(9_500, 6_500 + 1_500 * (hits - 1))}


class MockGuardModel:
    name = "mock"
    model_id = "mock-guard-v1"
    is_mock = True

    def __init__(self, score_fn: Callable[[str], GuardScore] | None = None) -> None:
        self._fn = score_fn or mock_score
        self.calls: list[list[str]] = []  # every batch handed to score(), for tests

    def score(self, texts: Sequence[str]) -> list[GuardScore]:
        self.calls.append(list(texts))
        return [self._fn(t) for t in texts]

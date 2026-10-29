"""WP-B1 item 4: the watcher compares word sequences (no page numbers, part headings or line
breaks). Layout-only differences are reported as ``layout_only``, never as ``text_changed``."""

from __future__ import annotations

import hashlib
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest

from supervisor.regkb import watch
from tests.regkb.test_w1_watch import check, fx, make_instrument


def _stored() -> str:
    return fx("docs.json")["docs"]["u-own-0001"]["_text"]


def _docs(text: str) -> dict[str, Any]:
    docs = fx("docs.json")["docs"]
    return {**docs, "u-own-0001": {**docs["u-own-0001"], "_text": text}}


@pytest.mark.parametrize(
    "variant",
    [
        lambda t: t.replace("\n", " "),  # lines merged
        lambda t: t.replace("\n", "\n\nTrang 2\n"),  # page-number lines between the lines
        lambda t: "- 1 -\n" + t.replace("Điều 3", "12/40\nĐiều 3"),
        lambda t: "Chương I\nQUY ĐỊNH CHUNG\n" + t,  # a part heading added
        lambda t: "Mục 2\n" + t.replace("\n", "\r\n"),
    ],
    ids=["merged", "page_lines", "page_numbers", "part_heading", "section_and_crlf"],
)
def test_layout_only_differences_are_not_a_change(
    tmp_path: Path, variant: Callable[[str], str]
) -> None:
    row, incoming = check(
        make_instrument(tmp_path), "search_unchanged.json", docs=_docs(variant(_stored()))
    )
    assert row["changes"] == [] and row["layout_only"] == ["u-own-0001"] and incoming == []


def test_a_heading_only_change_is_layout_only(tmp_path: Path) -> None:
    old = "Chương I\nQUY ĐỊNH CHUNG\n" + _stored()
    new = old.replace("Chương I\nQUY ĐỊNH CHUNG", "Chương II\nQUY ĐỊNH KHÁC")
    inst = make_instrument(tmp_path)
    sha = hashlib.sha256(old.encode("utf-8")).hexdigest()
    (inst.stored_dir / "99-2026.txt").write_text(old, encoding="utf-8")
    (inst.stored_dir / "99-2026.meta.json").write_text(f'{{"sha256": "{sha}"}}', encoding="utf-8")
    inst.sources[0]["sha256"] = sha
    row, incoming = check(inst, "search_unchanged.json", docs=_docs(new))
    assert row["changes"] == [] and row["layout_only"] == ["u-own-0001"] and incoming == []


def test_an_article_heading_or_word_change_still_counts(tmp_path: Path) -> None:
    for text in (
        _stored().replace("Điều 2. Giải thích từ ngữ.", "Điều 2. Giải thích khái niệm."),
        _stored().replace("tổ chức", "cá nhân"),
        _stored() + "\nĐiều 4. Mới.",
    ):
        row, _ = check(make_instrument(tmp_path), "search_unchanged.json", docs=_docs(text))
        assert [c["kind"] for c in row["changes"]] == ["text_changed"], text


def test_words_of_drops_only_the_noise() -> None:
    assert watch.words_of("A b\n\n12\nTrang 3\nc") == ["A", "b", "c"]
    assert watch.words_of("Chương III\nQUY ĐỊNH\nĐiều 1. X") == ["Điều", "1.", "X"]
    assert watch.words_of("Chương III\nNội dung thường") == ["Nội", "dung", "thường"]
    assert watch.words_of("Điều 12. Nghĩa vụ 30 ngày") == [
        "Điều",
        "12.",
        "Nghĩa",
        "vụ",
        "30",
        "ngày",
    ]

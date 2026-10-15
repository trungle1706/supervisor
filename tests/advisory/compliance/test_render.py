from __future__ import annotations

import dataclasses
import json

from supervisor.advisory.compliance.model import Narrative
from supervisor.advisory.compliance.render import (
    to_html,
    to_json,
    to_markdown,
    write_all,
)
from supervisor.regkb import DISCLAIMER

from ._factory import tiny_matrix


def test_json_is_stable_and_sorted():
    a, b = to_json(tiny_matrix()), to_json(tiny_matrix())
    assert a == b
    data = json.loads(a)
    assert list(data) == sorted(data)
    assert data["header"]["disclaimer"] == DISCLAIMER
    assert [r["obligation_id"] for r in data["rows"]] == ["OB-1", "OB-2", "OB-3"]


def test_md_and_html_have_disclaimer_twice():
    m = tiny_matrix()
    assert to_markdown(m).count(DISCLAIMER) == 2
    assert to_html(m).count(DISCLAIMER) == 2


def test_bilingual_status_and_applies_words():
    m = tiny_matrix()
    for text in (to_markdown(m), to_html(m)):
        assert "Gap / Thiếu" in text
        assert "Partial / Một phần" in text
        assert "Not applicable / Không áp dụng" in text or "Không áp dụng" in text
        assert "Applies / Áp dụng" in text
        assert "Needs answer / Cần trả lời" in text


def test_mock_narrative_is_labelled():
    n = Narrative("A short text.", "mock-chat-v1", True)
    for text in (to_markdown(tiny_matrix(narrative=n)), to_html(tiny_matrix(narrative=n))):
        assert "mock" in text
        assert "A short text." in text
    real = Narrative("Real text.", "gpt-x", False)
    assert "mock / " not in to_markdown(tiny_matrix(narrative=real))
    assert "[advisory / tham khảo]" in to_markdown(tiny_matrix(narrative=real))


def test_no_narrative_section_without_narrative():
    assert "Narrative" not in to_markdown(tiny_matrix())


def test_html_escapes_internal_rule_text_and_loads_nothing():
    evil = "<script>alert(1)</script>"
    out = to_html(tiny_matrix(evil=evil))
    assert evil not in out
    assert "&lt;script&gt;alert(1)&lt;/script&gt;" in out
    assert "<script" not in out
    assert "http://" not in out and "https://" not in out
    assert "&lt;One&gt;" in out  # product name is escaped too


def test_not_applicable_rows_are_collapsed():
    m = tiny_matrix()
    html_text = to_html(m)
    assert "<details>" in html_text and "OB-3" in html_text
    md = to_markdown(m)
    assert "\n| OB-3 |" not in md and "OB-3" in md


def test_applies_yes_rows_first():
    md = to_markdown(tiny_matrix())
    assert md.index("\n| OB-1 |") < md.index("\n| OB-2 |")


def test_md_table_escapes_pipe():
    m = tiny_matrix(evil="a | b")
    assert "a \\| b" in to_markdown(m)


def test_write_all(tmp_path):
    paths = write_all(tiny_matrix(), tmp_path / "out")
    assert set(paths) == {"json", "md", "html"}
    assert {p.name for p in paths.values()} == {
        "compliance_matrix.json",
        "compliance_matrix.md",
        "compliance_matrix.html",
    }
    assert all(p.read_text(encoding="utf-8") for p in paths.values())


def test_vietnamese_source_text_not_translated():
    m = tiny_matrix()
    row = dataclasses.replace(m.rows[0], summary_en="Nghĩa vụ giữ nguyên")
    m = dataclasses.replace(m, rows=(row,) + m.rows[1:])
    assert "Nghĩa vụ giữ nguyên" in to_markdown(m)

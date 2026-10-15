"""WP12: Cases table - plain headline, rule + case id, opened-by pill, clock bar, archive."""

from __future__ import annotations

import re

from .conftest import Console


def test_cases_table_rows(console: Console) -> None:
    r = console.get("/console/cases")
    assert r.status_code == 200, r.text
    row = r.text.split('data-case="', 2)[1]
    assert re.search(r"(paused|blocked) before it ran", r.text)
    assert re.search(r"[A-Z]{3}-\d{2} · CASE-[0-9A-F]+", r.text)  # rule id + case id (mono)
    assert "src-gate" in row and ">gate<" in row
    assert 'class="clockcell"' in row and "h " in row and "left" in row
    assert "Refresh cases" in r.text
    assert "The clocks come from the draft SBV circular" in r.text  # the why line


def test_case_filters_and_archive(console: Console) -> None:
    judge = console.get("/console/queue/rows?source=judge")
    assert judge.status_code == 200 and 'data-case="' not in judge.text
    gate = console.get("/console/queue/rows?source=gate")
    assert gate.text.count('data-case="') == 4
    archive = console.get("/console/cases?status=closed")
    assert archive.status_code == 200 and "Archive" in archive.text
    assert 'data-case="' not in archive.text and "No cases." in archive.text
    bad = console.get("/console/queue/rows?source=nope", headers={"HX-Request": "true"})
    assert bad.status_code == 400 and "unknown opened-by filter" in bad.text


def test_cases_in_vietnamese(console: Console) -> None:
    r = console.get("/console/cases?lang=vi")
    assert "trước khi chạy" in r.text and "Mở bởi" in r.text and "còn " in r.text

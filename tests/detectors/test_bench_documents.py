"""WP-D1: the document intake benchmark tool runs (small size; numbers: docs/latency.md)."""

from __future__ import annotations

import pytest

from tools import bench_documents as B


def test_bench_runs_on_a_small_document(capsys: pytest.CaptureFixture[str]) -> None:
    pytest.importorskip("pypdf")
    rows = B.bench(5, 3)
    assert [r["kind"] for r in rows] == ["txt", "docx", "pdf"]
    for r in rows:
        assert r["text_chars"] > 4000 and r["total_p50_us"] >= r["score_p50_us"] > 0
        assert all(isinstance(v, int) for k, v in r.items() if k.endswith("_us"))
    assert B.main(["--kb", "5", "--runs", "3"]) == 0
    assert capsys.readouterr().out.isascii()

"""jobs.ingest: drains the spool into agent_event, idempotent by event_id."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from supervisor.adapters.factory import Adapters
from supervisor.adapters.masking.vn_regex import VnRegexMasker
from supervisor.jobs import ingest
from supervisor.recorder.capture import AgentCapture, CapturePolicy
from supervisor.recorder.normalise import Normaliser, span_from_readable, spans_to_otlp_json
from supervisor.recorder.service import build_recorder
from supervisor.recorder.sink import Spool
from tests.recorder.conftest import PII_NAME, payments_spans

POLICY = CapturePolicy({"payments": AgentCapture("masked")})


SPANS = payments_spans()


def _fill_spool(directory: Path, masker: VnRegexMasker) -> None:
    spans = SPANS
    items = Normaliser(masker, POLICY).normalise_many(
        [span_from_readable(s) for s in spans], "otel"
    )
    spool = Spool(directory)
    spool.put_rows([i.event for i in items[:4]], [])
    spool.put_rows([i.event for i in items[2:]], [])  # overlap: 2 rows twice
    spool.put_otlp(spans_to_otlp_json(spans))  # same spans via OTLP: other source, same ids
    with (directory / "agent-written.jsonl").open("w", encoding="utf-8") as fh:
        fh.write("garbage line\n")
        fh.write(json.dumps({"kind": "nope"}) + "\n")


def test_ingest_drains_spool_idempotently(
    adapters: Adapters, masker: VnRegexMasker, tmp_path: Path
) -> None:
    spool_dir = tmp_path / "spool"
    _fill_spool(spool_dir, masker)
    rec = build_recorder(adapters.settings, adapters.tables, masker=masker, policy=POLICY)
    first = ingest.run(adapters.settings, adapters, recorder=rec, spool_dir=spool_dir)
    assert first["written"] == 7 and first["rejected"] == 2 and first["files"] == 2
    assert first["duplicates"] == 2 + 7  # overlap + the OTLP copy of the same spans
    rows = adapters.tables.query("agent_event")
    assert len(rows) == 7 and len({r["event_id"] for r in rows}) == 7
    assert PII_NAME not in json.dumps(rows, default=str, ensure_ascii=False)
    assert sorted(p.suffix for p in spool_dir.iterdir()) == [".done", ".done", ".rejected"]

    # Re-spool everything and run again: nothing new is written.
    _fill_spool(spool_dir, masker)
    second = ingest.run(adapters.settings, adapters, recorder=rec, spool_dir=spool_dir)
    assert second["written"] == 0 and second["duplicates"] == 4 + 5 + 7
    assert len(adapters.tables.query("agent_event")) == 7


def test_store_failure_keeps_file_for_next_run(
    adapters: Adapters, masker: VnRegexMasker, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    spool_dir = tmp_path / "spool"
    _fill_spool(spool_dir, masker)
    rec = build_recorder(adapters.settings, adapters.tables, masker=masker, policy=POLICY)
    real = adapters.tables.append
    calls = {"n": 0}

    def flaky(table, rows):
        calls["n"] += 1
        if calls["n"] == 2:
            raise RuntimeError("warehouse unavailable")
        return real(table, rows)

    monkeypatch.setattr(adapters.tables, "append", flaky)
    with pytest.raises(RuntimeError):
        ingest.run(adapters.settings, adapters, recorder=rec, spool_dir=spool_dir)
    assert list(spool_dir.glob("*.ingesting"))
    monkeypatch.setattr(adapters.tables, "append", real)
    again = ingest.run(adapters.settings, adapters, recorder=rec, spool_dir=spool_dir)
    assert len(adapters.tables.query("agent_event")) == 7
    assert not list(spool_dir.glob("*.ingesting")) and again["files"] == 1


def test_cli_main_ascii(
    adapters: Adapters,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setenv("SQL_BACKEND", "sqlite")
    monkeypatch.setenv("DATA_DIR", str(adapters.settings.data_dir))
    log = tmp_path / "p.jsonl"
    log.write_text(
        json.dumps(
            {"ts": "2026-10-14T05:00:00Z", "agent_id": "vendor_bot", "request_id": "r1",
             "kind": "tool_call", "tool": "x", "args": {"memo": "Nguyễn Gia Tuấn"}},
            ensure_ascii=False,
        ) + "\n",
        encoding="utf-8",
    )  # fmt: skip
    assert ingest.main(["--proxy-log", str(log)]) == 0
    out = capsys.readouterr().out
    assert out.startswith("[OK] ingest:") and out.isascii() and "written=1" in out
    assert ingest.main(["--proxy-log", str(log)]) == 0
    assert "written=0" in capsys.readouterr().out
    assert len(adapters.tables.query("trace_coverage")) == 1
    assert ingest.main(["--proxy-log", str(tmp_path / "missing.jsonl")]) == 1
    assert capsys.readouterr().out.startswith("[FAIL]")


def test_poison_lines_are_rejected_without_text_and_do_not_stall(
    adapters: Adapters, masker: VnRegexMasker, tmp_path: Path
) -> None:
    spool_dir = tmp_path / "spool"
    spool_dir.mkdir()
    good = Normaliser(masker, POLICY).normalise_many([span_from_readable(SPANS[0])], "otel")
    row = {**good[0].event.row(), "ts": "2026-10-14T05:00:00Z", "amount_minor": 10**30}
    lines = [
        json.dumps({"kind": "rows", "agent_event": [row], "agent_event_raw": []}),
        json.dumps({"kind": "otlp", "payload": {"resourceSpans": "0912345678"}}),
    ]
    (spool_dir / "x.jsonl").write_text("\n".join(lines) + "\n", encoding="utf-8")
    rec = build_recorder(adapters.settings, adapters.tables, masker=masker, policy=POLICY)
    out = ingest.run(adapters.settings, adapters, recorder=rec, spool_dir=spool_dir)
    assert out["rejected"] == 2 and out["files"] == 1
    rejected = (spool_dir / "x.rejected").read_text(encoding="utf-8")
    assert "0912345678" not in rejected and "line_sha256" in rejected
    assert not list(spool_dir.glob("*.ingesting"))

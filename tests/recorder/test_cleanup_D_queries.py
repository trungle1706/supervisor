"""Clean-up audit N17: a replay (every row already stored) finds the stored ids with one read
per table, not one query per event, and counts the same duplicates."""

from __future__ import annotations

from typing import Any

from supervisor.adapters.factory import Adapters
from supervisor.adapters.masking.vn_regex import VnRegexMasker
from supervisor.adapters.sql.store import SqlTableStore
from supervisor.recorder.capture import AgentCapture, CapturePolicy
from supervisor.recorder.normalise import Normaliser, span_from_readable
from supervisor.recorder.sink import EventWriter
from tests.recorder.conftest import payments_spans
from tests.test_store_read_cache import Counting

POLICY = CapturePolicy({"payments": AgentCapture("masked")})


def _items(masker: VnRegexMasker) -> list[Any]:
    spans = payments_spans()
    return Normaliser(masker, POLICY).normalise_many([span_from_readable(s) for s in spans], "otel")


def _replay(adapters: Adapters, items: list[Any], take: int) -> tuple[int, int, int]:
    x = Counting(adapters.executor.path)
    writer = EventWriter(SqlTableStore(x))
    batch = items[:take]
    first = writer.write(batch)
    before = x.reads
    again = writer.write(batch)
    return first.written, again.duplicates, x.reads - before


def test_replay_reads_do_not_grow_with_the_batch(adapters: Adapters, masker: VnRegexMasker) -> None:
    items = _items(masker)
    n_all = len(items)
    assert n_all >= 5
    w_small, dup_small, reads_small = _replay(adapters, items, 2)
    # the first call stored 2 rows; the second call replays them; then a bigger batch
    w_big, dup_big, reads_big = _replay(adapters, items, n_all)
    assert w_small == 2 and dup_small == 2
    assert w_big == n_all - 2 and dup_big == n_all  # the 2 stored rows were duplicates in the first
    assert reads_small == reads_big == 1

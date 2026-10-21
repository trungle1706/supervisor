"""Recorder service: normaliser + writer, built once from Settings."""

from __future__ import annotations

import threading
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from supervisor.config import Settings
from supervisor.core.ports import Masker, TableStore
from supervisor.recorder.capture import CapturePolicy, load_manifest_policy
from supervisor.recorder.normalise import Normaliser, Source, SpanData, spans_from_otlp_json
from supervisor.recorder.sink import EventWriter, Spool, WriteResult


@dataclass
class IngestResult(WriteResult):
    spans: int = 0
    ignored: int = 0  # spans that are not agent events (no agent id / event type)


class Recorder:
    def __init__(self, normaliser: Normaliser, writer: EventWriter) -> None:
        self.normaliser = normaliser
        self.writer = writer

    def ingest_spans(self, spans: list[SpanData], source: Source) -> IngestResult:
        items = self.normaliser.normalise_many(spans, source)
        res = self.writer.write(items)
        return IngestResult(
            res.written, res.duplicates, res.spooled, len(spans), len(spans) - len(items)
        )

    def ingest_otlp_json(self, payload: Mapping[str, Any], source: Source = "otlp") -> IngestResult:
        """Raises OtlpFormatError (user error) on a malformed payload; nothing is written then."""
        return self.ingest_spans(spans_from_otlp_json(payload), source)


def build_recorder(
    settings: Settings,
    tables: TableStore,
    *,
    masker: Masker | None = None,
    policy: CapturePolicy | None = None,
    use_spool: bool = True,
) -> Recorder:
    if masker is None:
        from supervisor.adapters.factory import make_masker

        masker = make_masker(settings)
    policy = policy or load_manifest_policy(default=settings.capture_default_level)
    spool: Spool | None = None
    if use_spool and settings.recorder_spool_dir:
        # WP10: a /Volumes spool path with no local mount (Databricks App) uses the Files API.
        from supervisor.databricks.files import make_spool

        spool = make_spool(settings)
    normaliser = Normaliser(
        masker,
        policy,
        "dev",
        use_semconv=settings.recorder_semconv,
        keep_correlation_id=settings.detectors_enabled,  # WP37
        keep_session_id=settings.session_monitor_enabled,  # WP27
    )
    return Recorder(normaliser, EventWriter(tables, spool))


_LOCK = threading.Lock()
_RECORDER: Recorder | None = None


def get_recorder() -> Recorder:
    """Process-wide recorder for the HTTP route (built lazily from get_settings())."""
    global _RECORDER
    with _LOCK:
        if _RECORDER is None:
            from supervisor.adapters.factory import build_adapters
            from supervisor.config import get_settings

            settings = get_settings()
            _RECORDER = build_recorder(settings, build_adapters(settings).tables)
        return _RECORDER


def set_recorder(recorder: Recorder | None) -> None:
    """Install (tests, wiring) or clear the process-wide recorder."""
    global _RECORDER
    with _LOCK:
        _RECORDER = recorder

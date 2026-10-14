"""JSON rendering: canonical bytes (sorted keys, no whitespace, UTF-8, no floats)."""

from __future__ import annotations

from supervisor.core.canonical import canonical_bytes
from supervisor.evidence.casefile.builder import CaseFile


def render_json(cf: CaseFile) -> bytes:
    return canonical_bytes(cf)


def parse_json(data: bytes) -> CaseFile:
    return CaseFile.model_validate_json(data)

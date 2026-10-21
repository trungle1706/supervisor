"""Transparency report (WP31, ADR D31, docs/transparency-report.md).

One report per agent, built from facts the system already holds, in three versions (regulator,
customer, internal), as JSON, HTML and PDF, in Vietnamese and English, signed into the evidence
chain and versioned. Off unless TRANSPARENCY_ENABLED=1.
"""

from supervisor.transparency.builder import ReportBuilder
from supervisor.transparency.facts import Facts, Sources
from supervisor.transparency.model import (
    FORMATS,
    LANGS,
    SECTIONS,
    VARIANTS,
    TransparencyError,
    TransparencyOff,
    UnknownAgent,
)
from supervisor.transparency.service import TransparencyService

__all__ = [
    "FORMATS",
    "LANGS",
    "SECTIONS",
    "VARIANTS",
    "Facts",
    "ReportBuilder",
    "Sources",
    "TransparencyError",
    "TransparencyOff",
    "TransparencyService",
    "UnknownAgent",
]

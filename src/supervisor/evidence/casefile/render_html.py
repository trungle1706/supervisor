"""HTML rendering: one self-contained page, inline CSS, no external assets."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta, timezone
from pathlib import Path

from jinja2 import Environment, FileSystemLoader, StrictUndefined

from supervisor.evidence.casefile.builder import CaseFile

ICT = timezone(timedelta(hours=7))
_TEMPLATE_DIR = Path(__file__).parent / "templates"


def fmt_utc(value: datetime | None) -> str:
    if value is None:
        return "-"
    return value.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def fmt_ict(value: datetime | None) -> str:
    if value is None:
        return "-"
    return value.astimezone(ICT).strftime("%Y-%m-%d %H:%M:%S ICT (UTC+7)")


def _env() -> Environment:
    env = Environment(
        loader=FileSystemLoader(str(_TEMPLATE_DIR)),
        autoescape=True,
        undefined=StrictUndefined,
        trim_blocks=True,
        lstrip_blocks=True,
    )
    env.filters["utc"] = fmt_utc
    env.filters["ict"] = fmt_ict
    return env


def render_html(cf: CaseFile) -> bytes:
    return _env().get_template("casefile.html.j2").render(cf=cf).encode("utf-8")

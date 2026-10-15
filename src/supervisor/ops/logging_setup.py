"""Structured logs (WP18). ``configure_logging(settings)`` is idempotent.

* ``LOG_FORMAT=text`` (default): ``time level logger: message``.
* ``LOG_FORMAT=json``: one JSON object per line with ``ts`` (RFC 3339 UTC), ``level``,
  ``logger``, ``msg``, ``request_id``, ``principal_id`` and, on errors, ``exc_type`` and ``exc``.
* Every message (and every argument, and any stack trace) goes through the PII scrubber, built
  on the in-repo regex masker (phone, CCCD/CMND, account numbers, e-mail, names). The
  ``principal_id`` field is the actor id and is exempt.
* ``LOG_FILE``: optional rotating UTF-8 file with the same format.
"""

from __future__ import annotations

import contextvars
import json
import logging
import logging.handlers
import os
import threading
from datetime import UTC, datetime
from typing import Any

from supervisor.adapters.masking.vn_regex import VnRegexMasker

# One mutable dict per request. Sync routes and dependencies run in a copied context (thread
# pool), so a plain ContextVar.set() there would be lost; mutating the shared dict is not.
log_ctx: contextvars.ContextVar[dict[str, str] | None] = contextvars.ContextVar(
    "sv_log_ctx", default=None
)


def begin_request(request_id: str) -> contextvars.Token[dict[str, str] | None]:
    return log_ctx.set({"request_id": request_id, "principal_id": "-"})


def end_request(token: contextvars.Token[dict[str, str] | None]) -> None:
    log_ctx.reset(token)


def _field(name: str) -> str:
    ctx = log_ctx.get()
    return ctx.get(name, "-") if ctx else "-"


TEXT_FORMAT = "%(asctime)s %(levelname)s %(name)s: %(message)s"
_TAG = "_sv_ops_handler"
_lock = threading.Lock()
# Tokens in logs are labels, not keyed pseudonyms: nothing in a log can be linked back.
_masker = VnRegexMasker(os.urandom(16), "log")


def set_principal_id(principal_id: str | None) -> None:
    """Put the actor id in the log context of the current request."""
    ctx = log_ctx.get()
    if ctx is not None:
        ctx["principal_id"] = principal_id or "-"


def scrub(text: str) -> str:
    """Replace every PII span with ``[TYPE]``."""
    if not text:
        return text
    try:
        text = _masker.canonical(text)  # span offsets refer to the normalised text
        spans = _masker.find(text)
    except Exception:  # noqa: BLE001 - logging must never raise
        return "[log text withheld: scrub error]"
    if not spans:
        return text
    out: list[str] = []
    pos = 0
    for sp in spans:
        out.append(text[pos : sp.start])
        out.append(f"[{sp.type}]")
        pos = sp.end
    out.append(text[pos:])
    return "".join(out)


class ScrubFilter(logging.Filter):
    """Scrub the message and its arguments in place (applies to any handler it is put on)."""

    def filter(self, record: logging.LogRecord) -> bool:
        try:
            msg = record.getMessage()
        except Exception:  # noqa: BLE001
            msg = str(record.msg)
        record.msg = scrub(msg)
        record.args = None
        return True


class TextFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        return scrub(super().format(record))


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        ts = datetime.fromtimestamp(record.created, UTC).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3]
        doc: dict[str, Any] = {
            "ts": ts + "Z",
            "level": record.levelname,
            "logger": record.name,
            "msg": scrub(record.getMessage()),
            "request_id": _field("request_id"),
            "principal_id": _field("principal_id"),
        }
        if record.exc_info and record.exc_info[0] is not None:
            doc["exc_type"] = record.exc_info[0].__name__
            doc["exc"] = scrub(self.formatException(record.exc_info))
        return json.dumps(doc, ensure_ascii=False)


def _level(name: str) -> int:
    value = logging.getLevelName(str(name).upper())
    return value if isinstance(value, int) else logging.INFO


def configure_logging(settings: Any) -> None:
    """Install (or re-install) the process log handlers. Safe to call many times."""
    with _lock:
        root = logging.getLogger()
        for h in [h for h in root.handlers if getattr(h, _TAG, False)]:
            root.removeHandler(h)
            h.close()
        fmt: logging.Formatter = (
            JsonFormatter() if settings.log_format == "json" else TextFormatter(TEXT_FORMAT)
        )
        handlers: list[logging.Handler] = [logging.StreamHandler()]
        if settings.log_file is not None:
            path = settings.log_file
            try:
                path.parent.mkdir(parents=True, exist_ok=True)
                handlers.append(
                    logging.handlers.RotatingFileHandler(
                        path,
                        maxBytes=settings.log_file_max_bytes,
                        backupCount=settings.log_file_backups,
                        encoding="utf-8",
                    )
                )
            except OSError:
                logging.getLogger("supervisor.ops").warning("log file cannot be opened")
        for h in handlers:
            h.setFormatter(fmt)
            h.addFilter(ScrubFilter())
            setattr(h, _TAG, True)
            root.addHandler(h)
        root.setLevel(_level(settings.log_level))
        # uvicorn installs its own handlers; send its records through ours.
        for name in ("uvicorn", "uvicorn.error", "uvicorn.access"):
            lg = logging.getLogger(name)
            lg.handlers = [h for h in lg.handlers if getattr(h, _TAG, False)]
            lg.propagate = True


__all__ = [
    "JsonFormatter",
    "ScrubFilter",
    "TextFormatter",
    "configure_logging",
    "begin_request",
    "end_request",
    "log_ctx",
    "scrub",
    "set_principal_id",
]

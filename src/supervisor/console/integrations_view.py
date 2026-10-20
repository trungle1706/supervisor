"""Integrations status page (WP-UX3, read-only): SIEM sink, webhook notifier, pager, ITSM, SCIM.

Per integration: configured, enabled, last delivery and dead-letter count. Secrets, tokens and
URLs are never shown (only the host name of a configured URL). Pager, ITSM and SCIM are stubs
with in-memory fakes until the bank wires them (WP11), and the page says so. Nothing is sent
and nothing is written; the dead-letter files are only counted."""

from __future__ import annotations

from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from supervisor.adapters.integrations import is_placeholder, load_integration_settings


def count_lines(path: Path | None) -> int | None:
    """Lines in a dead-letter file (0 when absent, None when it cannot be read)."""
    if path is None:
        return None
    try:
        if not path.exists():
            return 0
        n = 0
        with path.open("rb") as fh:
            for chunk in iter(lambda: fh.read(1 << 16), b""):
                n += chunk.count(b"\n")
        return n
    except OSError:
        return None


def host_of(url: str) -> str | None:
    if is_placeholder(url):
        return None
    try:
        return urlparse(url).hostname or None
    except ValueError:
        return None


def _latest(values: list[Any]) -> Any:
    values = [v for v in values if v is not None]
    return max(values) if values else None


def _siem(ctx: Any, cfg: Any) -> dict[str, Any]:
    cursors = ctx.state.query("monitor_state", {"monitor": "siem"})
    host = host_of(cfg.siem_webhook_url) if cfg.siem_sink in ("http", "webhook") else None
    needs_url = cfg.siem_sink in ("http", "webhook")
    dl = None
    if needs_url:
        dl = count_lines(
            cfg.siem_dead_letter_path or Path(ctx.settings.data_dir) / "siem" / "dead_letter.jsonl"
        )
    return {
        "key": "siem",
        "enabled": bool(cfg.siem_enabled),
        "configured": bool(host) if needs_url else True,
        "stub": False,
        "detail": f"{cfg.siem_sink} / {cfg.siem_format}" + (f" / {host}" if host else ""),
        "last": _latest([r.get("updated_at") for r in cursors]),
        "lanes": len([r for r in cursors if str(r["state_key"]).startswith("cursor:")]),
        "dead_letter": dl,
    }


def _webhook(ctx: Any) -> dict[str, Any]:
    from supervisor.adapters.notify import webhook_dead_letter_path

    s = ctx.settings
    sent = [
        r
        for r in ctx.state.query("notice", {"status": "sent"})
        if str(r["channel"]).startswith("webhook:")
    ]
    queued = [
        r
        for r in ctx.state.query("notice", {"status": "queued"})
        if str(r["channel"]).startswith("webhook:")
    ]
    dead = [
        r
        for r in ctx.state.query("notice", {"status": "dead_letter"})
        if str(r["channel"]).startswith("webhook:")
    ]
    host = host_of(s.notify_webhook_url)
    file_n = count_lines(webhook_dead_letter_path(s))
    return {
        "key": "webhook",
        "enabled": bool(s.notify_webhook_enabled),
        "configured": bool(host),
        "stub": False,
        "detail": (host or "") + (" / token set" if s.notify_webhook_token else ""),
        "last": _latest([r.get("updated_at") for r in sent]),
        "queued": len(queued),
        "dead_letter": (file_n or 0) + len(dead) if file_n is not None else len(dead),
    }


def _itsm(ctx: Any, cfg: Any) -> dict[str, Any]:
    refs = [c for c in ctx.state.query("cases") if c.get("itsm_ref")]
    return {
        "key": "itsm",
        "enabled": bool(cfg.itsm_enabled),
        "configured": False,
        "stub": True,
        "detail": f"{len(refs)} case(s) with a ticket reference",
        "last": _latest([c.get("updated_at") for c in refs]),
        "dead_letter": None,
    }


def _stub(key: str, enabled: bool) -> dict[str, Any]:
    return {
        "key": key,
        "enabled": bool(enabled),
        "configured": False,
        "stub": True,
        "detail": "",
        "last": None,
        "dead_letter": None,
    }


def page(ctx: Any) -> dict[str, Any]:
    cfg = load_integration_settings()
    rows = [
        _siem(ctx, cfg),
        _webhook(ctx),
        _stub("pager", cfg.pager_enabled),
        _itsm(ctx, cfg),
        _stub("scim", cfg.scim_enabled),
    ]
    return {"rows": rows, "dead_total": sum(r["dead_letter"] or 0 for r in rows)}

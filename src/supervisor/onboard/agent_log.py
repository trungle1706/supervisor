"""The agent log (WP-O5, phase 9, flag ``ONBOARD_POSTDEPLOY``).

One append-only ``onboard_log`` row for every onboarding action of a candidate or an agent: the
scan found it, a source was taken in, the facts were read, the pre-deploy assessment started and
gave a verdict, a person checked the attachment, asked for RUNNING or approved it, the duties
step was submitted. The console shows the rows as a timeline "plan, read, found, suggest" with a
pill for who acted: ``rule`` (deterministic code), ``model`` or ``person``.

Rules:

* ``log`` never raises. A hook that fails writes one WARNING and the action it logs goes on.
* With the flag off ``log`` does nothing (no read, no write).
* ``what`` and ``pointer`` are cut to 300 and 200 characters, secrets go through the onboarding
  scrubber and personal data (name, phone, address, card or account number) through the
  Vietnamese regex masker, which is only used to find spans: a span becomes ``[pii]``. The hooks
  build ``what`` from fixed sentences, counts and ids; they never copy a file name, a URL, a
  reason typed by a person or a line of source.
* No floats: counts are integers.

``ctx`` is any object with ``settings``, ``clock`` and ``tables`` (the console context, or a
service that was given ``tables``); a service without ``tables`` logs nothing.
"""

from __future__ import annotations

import logging
import uuid
from collections.abc import Mapping
from typing import Any

from supervisor.core.canonical import format_ts
from supervisor.onboard.scrub import scrub_text

log_ = logging.getLogger("supervisor.onboard.agent_log")

STEPS = (
    "scan",
    "intake",
    "facts",
    "predeploy",
    "attach",
    "postdeploy",
    "state",
    "duties",
    "orchestrate",
)
BY_KINDS = ("model", "rule", "person")
MAX_WHAT = 300
MAX_POINTER = 200
MAX_ACTOR = 120
TABLE = "onboard_log"
_PII_KEY = b"agent-log-span-finder"  # only finds spans; no token is ever written


def enabled(ctx: Any) -> bool:
    st = getattr(ctx, "settings", None)
    # the orchestrator (WP-F4) writes its plan and steps here too
    return bool(
        getattr(st, "onboard_postdeploy", False) or getattr(st, "onboard_orchestrator", False)
    )


def _masker() -> Any:
    from supervisor.adapters.masking.vn_regex import VnRegexMasker

    return VnRegexMasker(_PII_KEY)


def clean(text: Any, limit: int) -> str:
    """One line, secrets and personal data replaced, cut to ``limit`` characters."""
    raw = "".join(c if c == " " or ord(c) >= 32 else " " for c in str(text or ""))
    raw = " ".join(scrub_text(raw).text.split())
    try:
        m = _masker()
        out: list[str] = []
        pos = 0
        for sp in m.find(raw):
            out.append(raw[pos : sp.start])
            out.append("[pii]")
            pos = sp.end
        out.append(raw[pos:])
        raw = "".join(out)
    except Exception:  # noqa: BLE001 - the masker must not stop a log row; the cut still applies
        log_.debug("agent log: masker not available")
    return raw[:limit]


def log(
    ctx: Any,
    node_id: str,
    step: str,
    what: str,
    pointer: str,
    by_kind: str,
    actor: str,
    attempt_n: int | None = None,
) -> bool:
    """Append one row. Returns ``True`` when a row was written. Never raises."""
    try:
        if not enabled(ctx):
            return False
        tables = getattr(ctx, "tables", None)
        if tables is None:
            return False
        if step not in STEPS or by_kind not in BY_KINDS:
            log_.warning("agent log: bad step or by_kind (%s, %s)", step, by_kind)
            return False
        tables.append(
            TABLE,
            [
                {
                    "log_id": "olg_" + uuid.uuid4().hex[:24],
                    "node_id": str(node_id)[:200],
                    "attempt_n": None if attempt_n is None else int(attempt_n),
                    "step": step,
                    "what": clean(what, MAX_WHAT),
                    "pointer": clean(pointer, MAX_POINTER) or "-",
                    "by_kind": by_kind,
                    "actor": clean(actor, MAX_ACTOR) or "rule",
                    "at": ctx.clock.now(),
                }
            ],
        )
        return True
    except Exception as exc:  # noqa: BLE001 - a log row never fails the action it describes
        log_.warning("agent log: row not written (%s)", type(exc).__name__)
        return False


def rows(ctx: Any, node_id: str, limit: int = 200) -> list[dict[str, Any]]:
    """The newest ``limit`` rows of a node, oldest first, as plain dicts (``at`` as RFC 3339)."""
    found = ctx.tables.query(TABLE, {"node_id": node_id}, order_by=("-at",), limit=limit)
    out = [view(r) for r in found]
    out.reverse()
    return out


def view(row: Mapping[str, Any]) -> dict[str, Any]:
    at = row.get("at")
    return {
        "log_id": str(row["log_id"]),
        "node_id": str(row["node_id"]),
        "attempt_n": None if row.get("attempt_n") is None else int(row["attempt_n"]),
        "step": str(row["step"]),
        "what": str(row["what"]),
        "pointer": str(row["pointer"]),
        "by_kind": str(row["by_kind"]),
        "actor": str(row["actor"]),
        "at": format_ts(at) if at is not None and not isinstance(at, str) else at,
    }


__all__ = ["BY_KINDS", "STEPS", "enabled", "log", "rows", "view"]

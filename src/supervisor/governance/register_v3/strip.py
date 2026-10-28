"""The compliance strip of the nine-step workflow (WP-C3): articles per step, status by rule.

``config/register_v3_strip.yaml`` maps a step to RegKB obligation ids. Each entry names one rule
from the closed list ``RULES``. A rule reads the draft and the records of the system and answers
``met``, ``open`` or ``not_applicable`` with an evidence pointer (a record id). No model sets a
status. Not legal advice. Bank counsel must confirm.
"""

from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml

from supervisor.core.errors import SupervisorError
from supervisor.governance.register_v2 import model as rm

DEFAULT_CONFIG = Path(__file__).resolve().parents[4] / "config" / "register_v3_strip.yaml"
RULES: tuple[str, ...] = (
    "source_taken",
    "facts_built",
    "system_saved",
    "class_recorded",
    "class_approved",
    "dims_started",
    "dims_closed",
    "matrix_row",
    "guardians_saved",
    "predeploy_go",
    "stage_requested",
    "submitted",
)
WHEN: tuple[str, ...] = ("high", "medium_high")
STATUSES: tuple[str, ...] = ("met", "open", "not_applicable")
HIGHISH = ("high", "prohibited")
SHORT: dict[str, str] = {
    "VN-TT53-2026": "TT53",
    "VN-AI-2025": "Law",
    "VN-DEC142-2026": "Decree",
}


class StripError(SupervisorError):
    """A bad strip file (the message names the place)."""


@dataclass(frozen=True)
class Entry:
    id: str
    rule: str
    when: str = ""


def parse(doc: Any) -> dict[str, tuple[Entry, ...]]:
    if not isinstance(doc, dict) or set(doc) - {"version", "illustrative", "steps"}:
        raise StripError("register_v3_strip.yaml: keys are version, illustrative, steps")
    steps = doc.get("steps")
    if not isinstance(steps, dict) or set(steps) != set(rm.STEP_KEYS_V3):
        raise StripError(
            "register_v3_strip.yaml: steps must name exactly " + ", ".join(rm.STEP_KEYS_V3)
        )
    out: dict[str, tuple[Entry, ...]] = {}
    for key, items in steps.items():
        if not isinstance(items, list) or not items:
            raise StripError(f"register_v3_strip.yaml: steps.{key} must be a non-empty list")
        rows = []
        for i, it in enumerate(items):
            where = f"steps.{key}[{i}]"
            if not isinstance(it, dict) or set(it) - {"id", "rule", "when"}:
                raise StripError(f"register_v3_strip.yaml: {where} keys are id, rule, when")
            oid, rule, when = it.get("id"), it.get("rule"), it.get("when") or ""
            if not isinstance(oid, str) or not oid:
                raise StripError(f"register_v3_strip.yaml: {where}.id must be text")
            if rule not in RULES:
                raise StripError(f"register_v3_strip.yaml: {where}.rule must be one of {RULES}")
            if when and when not in WHEN:
                raise StripError(f"register_v3_strip.yaml: {where}.when must be one of {WHEN}")
            rows.append(Entry(oid, str(rule), str(when)))
        out[str(key)] = tuple(rows)
    return out


@lru_cache(maxsize=4)
def _load(path: str, mtime_ns: int) -> dict[str, tuple[Entry, ...]]:
    try:
        return parse(yaml.safe_load(Path(path).read_text(encoding="utf-8")))
    except (OSError, yaml.YAMLError):
        raise StripError("register_v3_strip.yaml: cannot read the file") from None


def load(path: Path | str | None = None) -> dict[str, tuple[Entry, ...]]:
    p = Path(path or DEFAULT_CONFIG)
    try:
        return _load(str(p), p.stat().st_mtime_ns)
    except OSError:
        raise StripError("register_v3_strip.yaml: cannot read the file") from None


def label_of(kb: Any, oid: str) -> dict[str, str]:
    o = kb.obligations.get(oid)
    if o is None:
        return {"instrument": "?", "article": oid, "summary": ""}
    return {
        "instrument": SHORT.get(o.instrument_id, o.number),
        "article": o.article_ref,
        "summary": o.summary_en,
    }


# ------------------------------------------------------------------------------ the rules


def _res(status: str, evidence: str = "") -> tuple[str, str]:
    return status, evidence


class Evidence:
    """What the rules read. Each property reads once; nothing here writes."""

    def __init__(self, ctx: Any, draft: dict[str, Any], key: str) -> None:
        self.ctx, self.draft, self.step_key = ctx, draft, key
        self.data = draft["data"]
        self.sid = str(
            self.data.get("sys") or (self.data.get("result") or {}).get("system_id") or ""
        )
        self._cache: dict[str, Any] = {}

    def once(self, name: str, fn: Any) -> Any:
        if name not in self._cache:
            try:
                self._cache[name] = fn()
            except Exception:  # noqa: BLE001 - a record that cannot be read is "open"
                self._cache[name] = None
        return self._cache[name]

    @property
    def src_key(self) -> str:
        from supervisor.governance.register_v3 import service as v3

        return v3.src_key(self.draft)

    @property
    def cls(self) -> dict[str, Any] | None:
        if not self.sid or not getattr(self.ctx.settings, "classification_v2", False):
            return None
        return self.once("cls", lambda: self.ctx.classification_v2.get(self.sid))

    @property
    def record(self) -> dict[str, Any] | None:
        got = self.cls
        return (got["current"] or got["pending"]) if got else None

    @property
    def level(self) -> str:
        rec = self.record
        return str(rec["level"] or "") if rec else ""

    @property
    def dims(self) -> list[dict[str, Any]]:
        from supervisor.governance import risk_dimensions as rd

        if not self.sid:
            return []
        return list(
            self.once("dims", lambda: rd.rows_of(rd.Env.from_console(self.ctx), self.sid)) or []
        )

    @property
    def approvals(self) -> list[dict[str, Any]]:
        if not self.sid:
            return []
        return list(self.once("appr", lambda: self.ctx.lifecycle.approvals(self.sid)) or [])

    def intake(self) -> list[dict[str, Any]]:
        if not getattr(self.ctx.settings, "onboard_intake", False):
            return []
        from supervisor.onboard.intake import IntakeService

        svc = IntakeService(self.ctx.settings, self.ctx.state, self.ctx.clock, self.ctx.tables)
        got = self.once("intake", lambda: svc.attempts(self.src_key)) or []
        return [a for a in got if a.get("status") != "failed"]

    def facts_attempt(self) -> int | None:
        if not getattr(self.ctx.settings, "onboard_facts", False):
            return None
        from supervisor.onboard.facts import FactsService

        svc = FactsService(
            self.ctx.settings, self.ctx.state, self.ctx.clock, tables=self.ctx.tables
        )
        card = self.once("facts", lambda: svc.card(self.src_key))
        return int(card["attempt_n"]) if card and card.get("attempt_n") is not None else None

    def predeploy(self) -> dict[str, Any] | None:
        if not getattr(self.ctx.settings, "onboard_predeploy", False):
            return None
        from supervisor.onboard.predeploy import PredeployService

        svc = PredeployService(self.ctx.settings, self.ctx.state, self.ctx.clock, ctx=self.ctx)
        return self.once("pd", lambda: svc.latest(self.src_key))

    def matrix_row(self, oid: str) -> Any:
        from supervisor.governance.register_v2 import duties as dut

        if not self.draft["data"]["v"].get("user_segment"):
            return None
        m = self.once("matrix", lambda: dut.matrix_of(self.ctx, self.draft))
        if m is None:
            return None
        return next((r for r in m.rows if r.obligation_id == oid), None)


def _source_taken(ev: Evidence) -> tuple[str, str]:
    got = ev.intake()
    if got:
        return _res("met", f"intake_attempt:{ev.src_key}#{got[0]['n']}")
    if ev.data.get("skip_source"):
        return _res("not_applicable", f"registration_draft:{ev.draft['draft_id']}#skip_source")
    return _res("open")


def _facts_built(ev: Evidence) -> tuple[str, str]:
    n = ev.facts_attempt()
    return _res("met", f"facts:{ev.src_key}#{n}") if n is not None else _res("open")


def _system_saved(ev: Evidence) -> tuple[str, str]:
    return _res("met", f"ai_system:{ev.sid}") if ev.sid else _res("open")


def _class_recorded(ev: Evidence) -> tuple[str, str]:
    rec = ev.record
    return _res("met", f"classification_v2:{rec['classification_id']}") if rec else _res("open")


def _class_approved(ev: Evidence) -> tuple[str, str]:
    got = ev.cls
    cur = got["current"] if got else None
    return _res("met", f"classification_v2:{cur['classification_id']}") if cur else _res("open")


def _dims_started(ev: Evidence) -> tuple[str, str]:
    rows = ev.dims
    started = [r for r in rows if r["status"] != "not_started"]
    return _res("met", f"risk_dimension_status:{ev.sid}") if started else _res("open")


def _dims_closed(ev: Evidence) -> tuple[str, str]:
    rows = ev.dims
    closed = all(r["status"] in ("pass", "waived", "not_applicable") for r in rows)
    ok = len(rows) == 8 and closed
    return _res("met" if ok else "open", f"risk_dimension_status:{ev.sid}" if rows else "")


def _matrix_row(ev: Evidence, oid: str) -> tuple[str, str]:
    row = ev.matrix_row(oid)
    if row is None:
        return _res("open")
    ptr = f"obligation:{oid}"
    if row.applies == "no":
        return _res("not_applicable", ptr)
    return _res("met" if row.applies == "yes" and row.status == "met" else "open", ptr)


def _guardians_saved(ev: Evidence) -> tuple[str, str]:
    n = int((ev.data.get("step_attempts") or {}).get("guardians", 0))
    return (
        _res("met", f"registration_draft:{ev.draft['draft_id']}#guardians") if n else _res("open")
    )


def _predeploy_go(ev: Evidence) -> tuple[str, str]:
    rep = ev.predeploy()
    if rep and rep.get("verdict") == "go":
        return _res("met", f"predeploy_report:{rep['report_id']}")
    return _res("open", f"predeploy_report:{rep['report_id']}" if rep else "")


def _stage_requested(ev: Evidence) -> tuple[str, str]:
    for a in ev.approvals:
        if a["status"] in ("pending", "approved"):
            return _res("met", f"stage_approval:{a['approval_id']}")
    return _res("open")


def _submitted(ev: Evidence) -> tuple[str, str]:
    ok = ev.draft["status"] == "submitted"
    return _res("met", f"ai_system:{ev.sid}") if ok and ev.sid else _res("open")


def status_of(ev: Evidence, e: Entry) -> tuple[str, str]:
    """Status and evidence pointer of one entry."""
    if e.when:
        level = ev.level
        if level:
            applies = level in HIGHISH if e.when == "high" else level in (*HIGHISH, "medium")
            if not applies:
                return _res(
                    "not_applicable",
                    ev.record and f"classification_v2:{ev.record['classification_id']}" or "",
                )
        else:
            return _res("open")
    if e.rule == "matrix_row":
        return _matrix_row(ev, e.id)
    fn = {
        "source_taken": _source_taken,
        "facts_built": _facts_built,
        "system_saved": _system_saved,
        "class_recorded": _class_recorded,
        "class_approved": _class_approved,
        "dims_started": _dims_started,
        "dims_closed": _dims_closed,
        "guardians_saved": _guardians_saved,
        "predeploy_go": _predeploy_go,
        "stage_requested": _stage_requested,
        "submitted": _submitted,
    }[e.rule]
    return fn(ev)


def attempt_of(ev: Evidence, key: str) -> int:
    """The number of the latest attempt of the step: intake and facts reuse their own numbers."""
    if key == "source":
        got = ev.intake()
        return int(got[0]["n"]) if got else 0
    if key == "facts":
        return ev.facts_attempt() or 0
    return int((ev.data.get("step_attempts") or {}).get(key, 0))


def evaluate(ctx: Any, draft: dict[str, Any], key: str) -> dict[str, Any]:
    """The strip of one step: rows ``{id, instrument, article, summary, status, evidence, rule,
    when}``, the attempt number and the counts."""
    from supervisor.console.compliance_view import kb_for

    entries = load()[key]
    kb = kb_for(ctx.settings)
    ev = Evidence(ctx, draft, key)
    rows = []
    for e in entries:
        status, evidence = status_of(ev, e)
        rows.append(
            {
                "id": e.id,
                **label_of(kb, e.id),
                "status": status,
                "evidence": evidence,
                "rule": e.rule,
                "when": e.when,
            }
        )
    return {
        "step": key,
        "attempt": attempt_of(ev, key),
        "rows": rows,
        "counts": {s: sum(1 for r in rows if r["status"] == s) for s in STATUSES},
    }

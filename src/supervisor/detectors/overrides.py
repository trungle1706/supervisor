"""Per-agent detector setting overrides stored in the table ``detector_override`` (WP-B1).

Resolution (strongest first): the policy file (``agents.<id>.detectors.settings.<slug>.<key>``),
then these rows for the agent, then these rows for agent ``*``, then ``config/detectors.yaml``.
A key the policy file names is locked: a row for it is kept but not applied. Only values that the
detector catalogue accepts are written, and ``keep_args`` is refused (it is audited per agent and
only the policy file may set it). The floor rules of the guardian bindings are untouched: this
module never enables or disables a detector, it only sets values of settings.

Every write puts one ``detector_override`` record on the chain: ids, a hash of the value, an
actor ref. No value text, no floats.
"""

from __future__ import annotations

import json
import logging
import re
import threading
import time
from collections.abc import Mapping
from typing import Any

from supervisor.controls.model import actor_ref
from supervisor.core.canonical import format_ts, sha256_hex
from supervisor.core.errors import ConcurrencyError, SupervisorError

log = logging.getLogger(__name__)

TABLE = "detector_override"
RECORD_TYPE = "detector_override"
SOURCES = ("smart_guardian", "manual")
WILDCARD = "*"
NEVER_OVERRIDE = frozenset({("dlp_vn", "keep_args")})
MAX_TEXT = 200
MAX_LIST = 32
CACHE_TTL_S = 5.0
_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:/-]{0,127}$")
_KEY = re.compile(r"^[a-z][a-z0-9_]{0,63}$")
_gen = 0
_lock = threading.Lock()


class OverrideError(SupervisorError):
    """A refused override (HTTP 400). The message starts with a short code."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(f"{code}: {message}")
        self.code = code


def _check_value(value: Any) -> Any:
    if isinstance(value, (bool, int)):
        return value
    if isinstance(value, str):
        if not value or len(value) > MAX_TEXT:
            raise OverrideError("bad_value", f"text must be 1..{MAX_TEXT} characters")
        return value
    if isinstance(value, list):
        if len(value) > MAX_LIST or not all(
            isinstance(x, str) and 0 < len(x) <= 128 for x in value
        ):
            raise OverrideError("bad_value", f"a list holds at most {MAX_LIST} short texts")
        return list(value)
    raise OverrideError(
        "bad_value", "a value is a whole number, a text, true/false or a list of texts"
    )


class DetectorOverrideService:
    def __init__(
        self, state: Any, clock: Any, settings: Any, *, evidence: Any = None, registry: Any = None
    ) -> None:
        self.state = state
        self.clock = clock
        self.settings = settings
        self.evidence_sink = evidence
        self.registry = registry  # optional DetectorRegistry: values are checked against it

    # ------------------------------------------------------------------ read
    def rows(self, agent_id: str | None = None) -> list[dict[str, Any]]:
        where = {"agent_id": agent_id} if agent_id else {}
        out = [dict(r) for r in self.state.query(TABLE, where)]
        out.sort(key=lambda r: (r["agent_id"], r["slug"], r["setting"]))
        return out

    def for_agent(self, agent_id: str) -> dict[str, dict[str, Any]]:
        """``slug -> {setting: value}``: the ``*`` rows, then the agent's own on top."""
        merged: dict[str, dict[str, Any]] = {}
        for who in (WILDCARD, agent_id):
            for r in self.rows(who):
                box = r["value"]
                if not isinstance(box, dict) or "v" not in box:
                    continue
                v = box["v"]
                merged.setdefault(str(r["slug"]), {})[str(r["setting"])] = v
        return merged

    # ----------------------------------------------------------------- write
    def set(
        self,
        agent_id: str,
        slug: str,
        setting: str,
        value: Any,
        actor: str,
        *,
        source: str = "manual",
        note: str | None = None,
    ) -> dict[str, Any]:
        if not isinstance(agent_id, str) or not (agent_id == WILDCARD or _ID.match(agent_id)):
            raise OverrideError("bad_agent", "agent id is not valid")
        if not isinstance(slug, str) or not _KEY.match(slug) or not _KEY.match(str(setting)):
            raise OverrideError("bad_key", "detector and setting names are lower-case words")
        if not isinstance(actor, str) or not actor:
            raise OverrideError("bad_actor", "a person must be named")
        if source not in SOURCES:
            raise OverrideError("bad_source", f"source is one of {', '.join(SOURCES)}")
        if (slug, setting) in NEVER_OVERRIDE:
            raise OverrideError(
                "locked_setting", f"{slug}.{setting} is set in the policy file only"
            )
        value = _check_value(value)
        if self.registry is not None:
            if slug not in self.registry:
                raise OverrideError("unknown_detector", f"{slug} is not in the catalogue")
            _, errs = self.registry.validate_settings(slug, {setting: value})
            errs = [e for e in errs if setting in str(e)]
            if errs:
                raise OverrideError("bad_value", "; ".join(str(e) for e in errs)[:300])
        now = self.clock.now()
        key = {"agent_id": agent_id, "slug": slug, "setting": setting}
        fields = {
            "value": {"v": value},  # boxed: a bare text is not valid JSON
            "source": source,
            "set_by": actor,
            "set_at": now,
            "note": str(note)[:300] if note else None,
        }
        with _lock:
            cur = self.state.get(TABLE, key)
            try:
                if cur is None:
                    row = self.state.insert(TABLE, {**key, **fields})
                else:
                    row = self.state.update(TABLE, key, fields, cur["row_version"])
            except ConcurrencyError:
                raise OverrideError("changed", "changed by someone else; try again") from None
            _bump()
        self._chain(key, value, source, actor, now, "changed" if cur is not None else "added")
        return dict(row)

    def _chain(
        self, key: Mapping[str, str], value: Any, source: str, actor: str, now: Any, action: str
    ) -> None:
        if self.evidence_sink is None:
            return
        payload = {
            **key,
            "action": action,
            "value_sha256": sha256_hex(json.dumps(value, sort_keys=True)),
            "source": source,
            "actor_ref": actor_ref(self.settings, actor, "system"),
            "ts": format_ts(now),
        }
        try:
            self.evidence_sink.record(RECORD_TYPE, f"agent:{key['agent_id']}", payload)
        except Exception:  # noqa: BLE001 - the row is stored; go on
            log.exception("detector_override chain record failed")


def _bump() -> None:
    global _gen
    _gen += 1


class OverrideSource:
    """Read-only, cached lookup the gate calls. No rows change nothing."""

    def __init__(self, state: Any) -> None:
        self.state = state
        self._cache: dict[str, tuple[float, int, dict[str, dict[str, Any]]]] = {}

    def settings_for(self, agent_id: str) -> dict[str, dict[str, Any]]:
        hit = self._cache.get(agent_id)
        now = time.monotonic()
        if hit is not None and hit[1] == _gen and now - hit[0] < CACHE_TTL_S:
            return hit[2]
        try:
            got = DetectorOverrideService(self.state, None, None).for_agent(agent_id)
        except Exception:  # noqa: BLE001 - a read failure leaves the file settings in force
            log.exception("detector_override read failed")
            got = {}
        self._cache[agent_id] = (now, _gen, got)
        return got


def make_source(settings: Any, state: Any) -> OverrideSource | None:
    """None unless SMART_GUARDIAN and DETECTORS_ENABLED are on: the gate then does not call into
    this module (the off path)."""
    if state is None or not (
        getattr(settings, "smart_guardian", False) and getattr(settings, "detectors_enabled", False)
    ):
        return None
    return OverrideSource(state)

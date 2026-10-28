"""Live guardians in the gate (WP-G3): a ``live`` definition is a detector under the slug
``gf:<def_id>@<version>``, switched on for the agents in its scope through the per-agent override
(``AgentDetectors.enable``) that the detector gate already reads.

* The gate holds one :class:`LiveGuardians` (``DetectorGate.attach``); it is None unless
  GUARDIAN_FACTORY and DETECTORS_ENABLED are on, so the off path is the code as before.
* The list of live definitions is read from ``guardian_def`` every ``caps.SHADOW_CACHE_S``
  seconds, or at once after a move in this process (``bump``). A retired version is no longer in
  the list, so it is no longer enabled; its detector stays registered and unused.
* A guardian binding (``governance/guardians.py``) with the slug ``gf:<id>@<version>`` set to off
  disables it for the agents of one AI system, unless the system's guardian floor names the slug.
* The adapter never lets a guardian that did not run fail a risky call closed
  (``fail_closed_allowed``), and the gate clamps every action it has no rule for (R1).
"""

from __future__ import annotations

import json
import logging
import threading
import time
from typing import Any

from supervisor.guardian_factory import adapter, caps
from supervisor.guardian_factory.definition import validate_definition

log = logging.getLogger("supervisor.guardian_factory")
TABLE = "guardian_def"

_generation = 0


def bump() -> None:
    """Drop every cached list of shadow and live guardians in this process."""
    global _generation
    _generation += 1


def generation() -> int:
    return _generation


def gf_slug(def_id: str, version: int) -> str:
    return f"{caps.GF_PREFIX}{def_id}@{int(version)}"


def parse_slug(slug: str) -> tuple[str, int] | None:
    m = caps.GF_SLUG_RE.match(slug or "")
    return (m.group(1), int(m.group(2))) if m else None


def bindable(state: Any, slug: str) -> bool:
    """True when ``slug`` names a live guardian version (a binding may switch it off)."""
    got = parse_slug(slug)
    if got is None:
        return False
    row = state.get(TABLE, {"def_id": got[0], "version": got[1]})
    return row is not None and str(row["state"]) == "live"


def live_slugs(state: Any) -> list[str]:
    rows = sorted(
        (dict(r) for r in state.query(TABLE, {"state": "live"})),
        key=lambda r: (str(r["def_id"]), int(r["version"])),
    )
    return [gf_slug(str(r["def_id"]), int(r["version"])) for r in rows]


def delegates_of(registry: Any) -> dict[str, Any]:
    return {s: registry.get(s) for s in caps.MODEL_REFS if s in registry}


def body_of(row: Any) -> dict[str, Any]:
    raw = row.get("definition_json")
    return dict(raw) if isinstance(raw, dict) else json.loads(raw or "{}")


class LiveGuardians:
    def __init__(
        self,
        state: Any,
        settings: Any,
        registry: Any,
        *,
        chat: Any = None,
        masker: Any = None,
        ttl_s: float = caps.SHADOW_CACHE_S,
    ) -> None:
        self.state = state
        self.settings = settings
        self.registry = registry
        self.chat = chat
        self.masker = masker
        self.ttl_s = ttl_s
        self._lock = threading.Lock()
        self._loaded = -1.0
        self._gen = -1
        self._items: list[tuple[str, Any]] = []  # (slug, scope.agents)

    def _entries(self) -> list[tuple[str, Any]]:
        now = time.monotonic()
        with self._lock:
            if self._gen == _generation and now - self._loaded < self.ttl_s:
                return self._items
            items: list[tuple[str, Any]] = []
            try:
                rows = sorted(
                    (dict(r) for r in self.state.query(TABLE, {"state": "live"})),
                    key=lambda r: (str(r["def_id"]), int(r["version"])),
                )
            except Exception:  # noqa: BLE001 - never break the gate; keep the last list
                log.exception("live guardian list not read")
                return self._items
            for r in rows:
                slug = gf_slug(str(r["def_id"]), int(r["version"]))
                try:
                    d = validate_definition(body_of(r))
                    if slug not in self.registry:
                        det = adapter.to_detector(
                            d,
                            delegates=delegates_of(self.registry),
                            chat=self.chat,
                            masker=self.masker,
                        )
                        det.slug = slug  # the registry key; findings carry it
                        self.registry.register(det)
                    items.append((slug, d.scope.agents))
                except Exception:  # noqa: BLE001 - one bad definition does not stop the others
                    log.exception("live guardian %s not attached", slug)
            self._items, self._loaded, self._gen = items, now, _generation
            return items

    def slugs_for(self, agent_id: str) -> list[str]:
        """The live guardian slugs whose scope names this agent (a consumer id has none of its
        own: the agent part counts)."""
        base = str(agent_id).split("/", 1)[0]
        return [s for s, agents in self._entries() if agents == "*" or base in agents]

    def deterministic(self, slug: str) -> bool:
        """True for a regex, keyword or policy guardian (the only ones that may block)."""
        det = self.registry.get(slug) if slug in self.registry else None
        return det is not None and getattr(det, "category", "") == "guardian"

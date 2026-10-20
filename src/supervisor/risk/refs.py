"""What a risk link may point at (WP29): the reference catalogue.

A link is only accepted when its target exists today:

=========  ==============================================================================
kind       target exists when
=========  ==============================================================================
matrix     the id is an obligation of the regulation knowledge base (one matrix row each)
rule       the id is a rule of the deployed policy (``rule`` table); if nothing is deployed
           yet (a fresh laptop), the rules of the policy folder
pack       the id is an assurance pack manifest
monitor    the name is a monitor of ``regulations/schema/controls.yaml``
case       the id is a row of ``cases``
=========  ==============================================================================

Each lookup is cached for the life of the object (a job run, a request). The class takes plain
callables in tests, so a unit test needs no database.
"""

from __future__ import annotations

import functools
from collections.abc import Callable, Iterable
from typing import Any

from supervisor.risk.model import RiskError


class RefCatalogue:
    def __init__(
        self,
        *,
        obligations: Callable[[], Iterable[str]] | None = None,
        rules: Callable[[], Iterable[str]] | None = None,
        packs: Callable[[], Iterable[str]] | None = None,
        monitors: Callable[[], Iterable[str]] | None = None,
        case_exists: Callable[[str], bool] | None = None,
    ) -> None:
        self._src = {"matrix": obligations, "rule": rules, "pack": packs, "monitor": monitors}
        self._case = case_exists
        self._cache: dict[str, frozenset[str]] = {}

    def clear(self) -> None:
        """Forget the cached lookups (call at the start of an operation)."""
        self._cache.clear()

    def ids(self, kind: str) -> frozenset[str]:
        if kind not in self._src:
            raise RiskError(f"no catalogue for link kind {kind!r}")
        if kind not in self._cache:
            fn = self._src[kind]
            self._cache[kind] = frozenset(fn()) if fn is not None else frozenset()
        return self._cache[kind]

    def exists(self, kind: str, target: str) -> bool:
        if kind == "case":
            return bool(self._case and self._case(target))
        return target in self.ids(kind)

    def check(self, kind: str, target: str) -> None:
        """RiskError when the target does not exist."""
        if not self.exists(kind, target):
            raise RiskError(f"{kind} {target!r} does not exist")

    def rule_ids(self) -> frozenset[str]:
        return self.ids("rule")


@functools.lru_cache(maxsize=1)
def _obligation_ids() -> tuple[str, ...]:
    from supervisor.regkb import load_kb

    return tuple(load_kb().obligations)


@functools.lru_cache(maxsize=1)
def _pack_ids() -> tuple[str, ...]:
    from supervisor.assurance.loader import load_packs

    return tuple(p.id for p in load_packs())


@functools.lru_cache(maxsize=1)
def _monitor_names() -> tuple[str, ...]:
    import yaml

    from supervisor.config import REPO_ROOT

    doc = yaml.safe_load((REPO_ROOT / "regulations" / "schema" / "controls.yaml").read_text())
    return tuple((doc.get("monitors") or {}).keys())


def build_catalogue(state: Any, settings: Any) -> RefCatalogue:
    """The catalogue over the live store and the repo files (lazy: nothing is read until used)."""

    def rules() -> list[str]:
        from supervisor.gateway.policy import MANIFEST_RULE_ID

        deployed = [
            r["rule_id"]
            for r in state.query("rule")
            if r.get("effective_to") is None and r["rule_id"] != MANIFEST_RULE_ID
        ]
        if deployed:
            return deployed
        from supervisor.config import REPO_ROOT
        from supervisor.gateway.policy import load_policy_dir

        folder = getattr(settings, "policy_dir", None) or (REPO_ROOT / "policies")
        return [r.id for r in load_policy_dir(folder).doc.rules]

    def case_exists(case_id: str) -> bool:
        return state.get("cases", {"case_id": case_id}) is not None

    return RefCatalogue(
        obligations=_obligation_ids,
        rules=rules,
        packs=_pack_ids,
        monitors=_monitor_names,
        case_exists=case_exists,
    )

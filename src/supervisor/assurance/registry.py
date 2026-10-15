"""Find the runner of a pack and select packs by id, dimension or ``all``.

Only modules under ``supervisor.assurance.runners.`` can be imported (the manifest regex
already says so; this is the second lock). ``overrides`` maps a manifest ``runner`` string
to an instance and exists for tests only.
"""

from __future__ import annotations

import importlib
from collections.abc import Mapping, Sequence
from typing import Any

from supervisor.assurance.model import DimensionT, EvalPack, PackRunner, TargetKind
from supervisor.core.errors import SupervisorError

RUNNER_PREFIX = "supervisor.assurance.runners."
DIMENSIONS: tuple[str, ...] = DimensionT.__args__  # type: ignore[attr-defined]


class RegistryError(SupervisorError):
    """A runner cannot be resolved or a selector is unknown."""


def resolve_runner(pack: EvalPack, overrides: Mapping[str, Any] | None = None) -> PackRunner:
    """Instance of the runner class named in ``pack.runner`` ("module:Class")."""
    if overrides and pack.runner in overrides:
        runner = overrides[pack.runner]
        if not callable(getattr(runner, "run", None)):
            raise RegistryError(f"{pack.id}: override for {pack.runner} has no run()")
        return runner  # type: ignore[no-any-return]
    module_name, _, class_name = pack.runner.partition(":")
    if not module_name.startswith(RUNNER_PREFIX) or not class_name:
        raise RegistryError(f"{pack.id}: runner must be '{RUNNER_PREFIX}<module>:<Class>'")
    try:
        module = importlib.import_module(module_name)
    except ImportError as exc:
        raise RegistryError(
            f"{pack.id}: runner module {module_name} not found ({type(exc).__name__})"
        ) from exc
    cls = getattr(module, class_name, None)
    if cls is None or not callable(cls):
        raise RegistryError(f"{pack.id}: runner class {class_name} not found in {module_name}")
    try:
        runner = cls()
    except Exception as exc:  # noqa: BLE001 - reported as a registry error
        raise RegistryError(f"{pack.id}: cannot build runner ({type(exc).__name__})") from exc
    if not callable(getattr(runner, "run", None)):
        raise RegistryError(f"{pack.id}: runner {class_name} has no run() method")
    return runner  # type: ignore[no-any-return]


def valid_selectors(packs: Sequence[EvalPack]) -> list[str]:
    return ["all", *DIMENSIONS, *sorted(p.id for p in packs)]


def select(
    packs: Sequence[EvalPack], selector: str, target_kind: TargetKind | None = None
) -> list[EvalPack]:
    """Packs chosen by ``selector`` (pack id, dimension name or ``all``).

    With ``target_kind`` only packs that list this kind in ``targets`` are returned. An
    unknown selector raises :class:`RegistryError` that lists the valid ones."""
    sel = selector.strip()
    if sel == "all":
        chosen = list(packs)
    elif sel in DIMENSIONS:
        chosen = [p for p in packs if p.dimension == sel]
    else:
        chosen = [p for p in packs if p.id == sel]
        if not chosen:
            raise RegistryError(
                f"unknown selector {selector!r}; valid: " + ", ".join(valid_selectors(packs))
            )
    if target_kind is not None:
        chosen = [p for p in chosen if target_kind in p.targets]
    return sorted(chosen, key=lambda p: p.id)

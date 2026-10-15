"""Case workflow (WP8). See ``supervisor.cases.service``."""

from __future__ import annotations

from typing import Any

from supervisor.cases.incident_clock import load_holidays
from supervisor.cases.service import (
    RESOLUTIONS,
    SEVERITIES,
    Actor,
    CaseError,
    CaseService,
    PermissionDenied,
    SystemActor,
    case_id_for,
)


def build_case_service(
    runtime: Any,
    *,
    system: Actor | None = None,
    notifier: Any = None,
    masker: Any = None,
) -> CaseService:
    """CaseService on a ``supervisor.wiring.Runtime`` (its store and its evidence chain)."""
    settings = runtime.settings
    if masker is None:
        from supervisor.adapters.factory import make_masker

        masker = make_masker(settings)
    mask_version = getattr(masker, "mask_version", None) or getattr(masker, "version", "") or ""
    return CaseService(
        runtime.adapters.state,
        runtime.adapters.tables,
        runtime.chain,
        runtime.adapters.clock,
        masker=masker,
        notifier=notifier,
        system=system,
        decision33_text=settings.casefile_decision33_text,
        mask_version=str(mask_version or settings.masker_kind),
        holidays=load_holidays(settings.incident_holidays_file),
    )


__all__ = [
    "RESOLUTIONS",
    "SEVERITIES",
    "Actor",
    "CaseError",
    "CaseService",
    "PermissionDenied",
    "SystemActor",
    "build_case_service",
    "case_id_for",
]

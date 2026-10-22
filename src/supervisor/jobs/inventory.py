"""Inventory refresh job (WP24): manifests, then the workspace, then the shadow-AI check.

Run: python -m supervisor.jobs.inventory [--fixture PATH] [--no-cases]
Also callable in-process (scheduler, INVENTORY_ENABLED=1 in databricks_app mode):
``run(adapters, settings, reader, cases)``.

Read only against the workspace. The standalone command opens cases (it writes to the evidence
chain), so run it only when the app is not running (single-writer rule); the app's scheduler
passes the console's case service instead.
"""

from __future__ import annotations

from supervisor.bootstrap import bootstrap

bootstrap()

import argparse  # noqa: E402
import sys  # noqa: E402
from pathlib import Path  # noqa: E402
from typing import Any  # noqa: E402

from supervisor.config import Settings  # noqa: E402
from supervisor.core.errors import SupervisorError  # noqa: E402
from supervisor.inventory.service import InventoryService  # noqa: E402


def build_reader(settings: Settings, fixture: Path | None = None) -> Any:
    """Fixture reader when a fixture is given or configured (offline), else the live SDK reader."""
    path = fixture or settings.inventory_workspace_fixture
    if path is not None:
        from supervisor.adapters.workspace.fixtures import FixtureWorkspaceReader

        return FixtureWorkspaceReader.from_file(path)
    from supervisor.adapters.workspace.databricks_sdk import DatabricksWorkspaceReader

    return DatabricksWorkspaceReader.from_settings(settings)


def scheduled(settings: Settings) -> bool:
    """The scheduler runs this job only with the flag on and a workspace (or a fixture)."""
    return bool(
        settings.inventory_enabled
        and (settings.supervisor_mode == "databricks_app" or settings.inventory_workspace_fixture)
    )


def run(
    adapters: Any,
    settings: Settings,
    reader: Any = None,
    cases: Any = None,
    systems: Any = None,
    tasks: Any = None,
) -> dict[str, Any]:
    """``systems`` and ``tasks`` (WP-G3) are the services that register a draft AI system; they
    are used only with ``INVENTORY_AUTOREGISTER=1`` and ``GOVERNANCE_ENABLED=1``. The scheduler
    passes the console's services (chain records); the standalone command builds its own."""
    svc = InventoryService.from_adapters(adapters)
    manifests = svc.fill_manifests()
    if settings.inventory_autoregister and settings.governance_enabled and systems is None:
        from supervisor.governance.systems import SystemService
        from supervisor.tasks.service import TaskService

        systems = SystemService.from_adapters(adapters)
        tasks = tasks or TaskService.from_adapters(adapters)
    out = svc.refresh_workspace(reader or build_reader(settings), cases, systems, tasks)
    out["manifests"] = manifests.as_dict()
    return out


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        prog="python -m supervisor.jobs.inventory",
        description="Refresh the inventory graph from manifests and the workspace.",
    )
    ap.add_argument("--fixture", type=Path, help="workspace JSON fixture (offline)")
    ap.add_argument("--no-cases", action="store_true", help="do not open shadow-AI cases")
    args = ap.parse_args(argv)
    from supervisor.cases import build_case_service
    from supervisor.config import load_settings
    from supervisor.wiring import build_runtime

    try:
        settings = load_settings()
        runtime = build_runtime(settings)
    except SupervisorError as exc:
        print(f"[FAIL] runtime: {exc}".encode("ascii", "replace").decode("ascii"))  # noqa: T201
        return 1
    try:
        if not settings.inventory_enabled:
            print("[SKIP] inventory is off (INVENTORY_ENABLED=1 turns it on)")  # noqa: T201
            return 0
        cases = None if args.no_cases else build_case_service(runtime)
        out = run(runtime.adapters, settings, build_reader(settings, args.fixture), cases)
    except (SupervisorError, OSError, ValueError) as exc:  # bad fixture path or JSON: no trace
        print(f"[FAIL] inventory: {exc}".encode("ascii", "replace").decode("ascii"))  # noqa: T201
        return 1
    finally:
        runtime.close()
    sh = out["shadow"]
    if "autoregister" in out:
        ar = out["autoregister"]
        print(  # noqa: T201
            f"[{'SKIP' if ar['status'] != 'ran' else 'OK'}] draft registration: "
            f"{ar['created']} created, {ar['already_registered']} already registered, "
            f"{ar['skipped_no_owner']} without a default owner"
            + (f" ({ar['reason']})" if ar.get("reason") else "")
        )
    print(  # noqa: T201
        f"[OK] inventory: {sh['managed']} managed, {sh['allowlisted']} allowlisted, "
        f"{sh['unmanaged']} unmanaged workspace item(s); errors: {out['errors'] or 'none'}"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))

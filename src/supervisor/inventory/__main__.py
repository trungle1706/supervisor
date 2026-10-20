"""Inventory CLI (WP24). ASCII output.

  python -m supervisor.inventory manifests            fill from agent manifests + baseline
  python -m supervisor.inventory onboarding PATH      fill from an onboarding inventory.json
  python -m supervisor.inventory show AGENT           print the agent's subgraph as a tree
  python -m supervisor.inventory unmanaged            list unmanaged workspace items
  python -m supervisor.inventory export --out DIR     inventory.json + two CSV files

Needs INVENTORY_ENABLED=1. The workspace refresh is ``python -m supervisor.jobs.inventory``.
"""

from __future__ import annotations

from supervisor.bootstrap import bootstrap

bootstrap()

import argparse  # noqa: E402
import sys  # noqa: E402
from pathlib import Path  # noqa: E402

from supervisor.core.errors import SupervisorError  # noqa: E402


def _say(text: str) -> None:
    print(text.encode("ascii", "replace").decode("ascii"))  # noqa: T201


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="python -m supervisor.inventory", description=__doc__)
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("manifests")
    p = sub.add_parser("onboarding")
    p.add_argument("path", type=Path)
    p = sub.add_parser("show")
    p.add_argument("agent")
    sub.add_parser("unmanaged")
    p = sub.add_parser("export")
    p.add_argument("--out", type=Path, required=True)
    args = ap.parse_args(argv)

    from supervisor.adapters.factory import build_adapters
    from supervisor.config import load_settings
    from supervisor.inventory.model import InventoryError
    from supervisor.inventory.service import InventoryService
    from supervisor.jobs import bootstrap_schema

    try:
        settings = load_settings()
        if not settings.inventory_enabled:
            _say("[SKIP] inventory is off (INVENTORY_ENABLED=1 turns it on)")
            return 0
        adapters = build_adapters(settings)
    except SupervisorError as exc:
        _say(f"[FAIL] {exc}")
        return 1
    try:
        if adapters.executor.dialect == "sqlite":
            bootstrap_schema.run(settings, adapters)
        svc = InventoryService.from_adapters(adapters)
        if args.cmd == "manifests":
            _say(f"[OK] manifests: {svc.fill_manifests().as_dict()}")
        elif args.cmd == "onboarding":
            _say(f"[OK] onboarding: {svc.fill_onboarding(args.path).as_dict()}")
        elif args.cmd == "show":
            view = svc.agent_view(args.agent)
            if view is None:
                _say(f"[FAIL] agent {args.agent} is not in the inventory")
                return 1
            _say(view["tree"])
        elif args.cmd == "unmanaged":
            rows = svc.unmanaged()
            for r in rows:
                _say(f"{r['kind']:15} {r['display_name']}  case={r.get('case_id') or '-'}")
            _say(f"[OK] {len(rows)} unmanaged item(s)")
        else:
            for p in svc.write_exports(args.out):
                _say(f"[OK] wrote {p}")
    except (SupervisorError, InventoryError, OSError) as exc:
        _say(f"[FAIL] {exc}")
        return 1
    finally:
        adapters.close()
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))

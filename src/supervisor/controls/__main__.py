"""Control catalogue CLI (WP30). ASCII output.

  python -m supervisor.controls list [--agent A] [--type T] [--status S]  controls, map counts
  python -m supervisor.controls import PATH --by USER [--dry-run] [--source starter]  import YAML
  python -m supervisor.controls status [--agent A] [--run --by USER]  evidence status, bp
  python -m supervisor.controls export --out DIR [--format json|csv|both]  controls.json, CSV files

Needs CONTROLS_ENABLED=1. ``status --run`` writes one status pass (as the job
``python -m supervisor.jobs.control_status`` does). The starter catalogue is in
config/controls/*.yaml; the bank's own catalogue is imported the same way (docs/controls.md).
Import the risks first when a control maps to risks: python -m supervisor.risk import config/risks
"""

from __future__ import annotations

from supervisor.bootstrap import bootstrap

bootstrap()

import argparse  # noqa: E402
import re  # noqa: E402
import sys  # noqa: E402
from pathlib import Path  # noqa: E402
from typing import TYPE_CHECKING  # noqa: E402

from supervisor.core.errors import SupervisorError  # noqa: E402

if TYPE_CHECKING:
    from supervisor.controls.service import ControlService


def _say(text: str) -> None:
    print(text.encode("ascii", "replace").decode("ascii"))  # noqa: T201


def _by(value: str) -> str:
    if not re.fullmatch(r"[A-Za-z0-9_.@+-]{1,64}", value):
        raise argparse.ArgumentTypeError(
            "--by must be 1 to 64 characters from A-Z a-z 0-9 _ . @ + -"
        )
    return value


def _audit(svc: object, by: str, permission: str, path: str, kind: str, detail: str) -> None:
    from supervisor.adapters.auth.audit import write_action

    write_action(
        svc.tables,  # type: ignore[attr-defined]
        svc.clock,  # type: ignore[attr-defined]
        request_id=None,
        actor=None,
        actor_fallback=(by, "operator", "cli"),
        permission=permission,
        method="CLI",
        path=path,
        outcome="ok",
        target_kind=kind,
        detail=detail,
    )


def _cut(text: str, n: int) -> str:
    return text if len(text) <= n else text[: n - 1] + "~"


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="python -m supervisor.controls", description=__doc__)
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("list")
    p.add_argument("--agent", default="")
    p.add_argument("--type", default="")
    p.add_argument("--status", default="")
    p.add_argument("--owner", default="")
    p = sub.add_parser("import")
    p.add_argument("path", type=Path)
    p.add_argument("--by", required=True, type=_by, help="who runs this import (your user id)")
    p.add_argument("--dry-run", action="store_true")
    p.add_argument("--overwrite-manual", action="store_true")
    p.add_argument("--source", choices=("import", "starter"), default="import")
    p = sub.add_parser("status")
    p.add_argument("--agent", default="")
    p.add_argument("--run", action="store_true", help="write a status pass first")
    p.add_argument("--by", default=None, type=_by, help="who runs the pass (needed with --run)")
    p = sub.add_parser("export")
    p.add_argument("--out", type=Path, required=True)
    p.add_argument("--format", choices=("json", "csv", "both"), default="both")
    args = ap.parse_args(argv)
    if args.cmd == "status" and args.run and not args.by:
        ap.error("status --run needs --by (your user id)")

    from supervisor.config import load_settings
    from supervisor.controls.service import ControlService

    try:
        settings = load_settings()
        if not settings.controls_enabled:
            _say("[SKIP] control catalogue is off (CONTROLS_ENABLED=1 turns it on)")
            return 0
        if args.cmd == "import" or (args.cmd == "status" and args.run):
            # a write: the changes go on the evidence chain, so open the chain writer too
            # (single writer per lane: stop the app first, see docs/controls.md)
            from supervisor.monitors.jobctx import standalone

            with standalone(settings) as (_, _adapters, ctx):
                svc = ControlService(
                    ctx.state, ctx.tables, ctx.clock, settings, evidence=ctx.evidence
                )
                return _do(args, svc)
        from supervisor.adapters.factory import build_adapters
        from supervisor.jobs import bootstrap_schema

        adapters = build_adapters(settings)
        try:
            if adapters.executor.dialect == "sqlite":
                bootstrap_schema.run(settings, adapters)
            return _do(args, ControlService.from_adapters(adapters))
        finally:
            adapters.close()
    except (SupervisorError, OSError) as exc:
        _say(f"[FAIL] {exc}")
        return 1


def _do(args: argparse.Namespace, svc: ControlService) -> int:
    if args.cmd == "list":
        rows = svc.list_controls(
            {
                "agent": args.agent,
                "type": args.type,
                "status": args.status,
                "owner": args.owner,
            }
        )
        _say(f"{'ID':20} {'TYPE':11} {'BY':8} {'STATUS':8} {'OBL':>3} {'RSK':>3} {'SRC':>3} TITLE")
        for r in rows:
            _say(
                f"{r['control_id']:20} {r['control_type']:11} {r['implemented_by']:8} "
                f"{r['status']:8} {r['matrix_n']:>3} {r['risk_n']:>3} {r['sources_n']:>3} "
                f"{_cut(r['title'], 50)}"
            )
        _say(f"[OK] {len(rows)} control(s)")
    elif args.cmd == "import":
        res = svc.import_path(
            args.path,
            args.by,
            source=args.source,
            dry_run=args.dry_run,
            overwrite_manual=args.overwrite_manual,
        )
        for e in res.errors:
            _say(f"[FAIL] {e}")
        for n in res.notes:
            _say(f"[SKIP] {n}")
        if res.errors:
            _say("[FAIL] nothing was imported")
            return 1
        if not args.dry_run:
            _audit(svc, args.by, "controls.edit", "supervisor.controls import", "control", "import")
        tag = "dry run: " if args.dry_run else ""
        _say(
            f"[OK] {tag}created={res.created} updated={res.updated} unchanged={res.unchanged} "
            f"skipped_manual={res.skipped_manual} maps_added={res.maps_added} "
            f"maps_removed={res.maps_removed}"
        )
    elif args.cmd == "status":
        if args.run:
            out = svc.run_status()
            _audit(svc, args.by, "controls.edit", "supervisor.controls status", "control", "status")
            _say("[OK] status pass: " + ", ".join(f"{k}={v}" for k, v in out.items()))
        _say(f"{'AGENT':20} {'IN SCOPE':>8} {'WORKING':>7} {'FAILING':>7} {'NO DATA':>7} {'BP':>6}")
        for name, _bp in sorted(svc.compliance_all().items()):
            if args.agent and name.lower() != args.agent.lower():
                continue
            c = svc.agent_compliance(name)
            bp = "-" if c["compliance_bp"] is None else str(c["compliance_bp"])
            _say(
                f"{name:20} {c['in_scope']:>8} {c['working']:>7} {c['failing']:>7} "
                f"{c['no_data']:>7} {bp:>6}"
            )
        _say("[OK] BP = controls with working evidence over controls in scope (integer bp)")
    else:
        for path in svc.write_exports(args.out, args.format):
            _say(f"[OK] wrote {path}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))

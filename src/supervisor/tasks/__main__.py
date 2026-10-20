"""Task list CLI (WP30). ASCII output.

  python -m supervisor.tasks list [--agent A] [--stage S] [--status S] [--required true]
  python -m supervisor.tasks plan --class C --band B           the planned set for a class and band
  python -m supervisor.tasks generate --agent A --by USER    make or complete the current stage
  python -m supervisor.tasks done TASK --by USER [--evidence-ref REF] [--role ROLE]
  python -m supervisor.tasks waive TASK --by USER --reason TEXT    ASK to waive (see below)

Needs CONTROLS_ENABLED=1. The CLI trusts the operator on the machine: ``--by`` is written to
the audit trail as given, and ``--role`` (default owner) is the role used for the lifecycle
approval rule. The second person of a waiver (approver or admin, a different person) can answer
only through the authenticated route ``POST /v1/tasks/<id>/waive/approve`` or the console, so a
waiver is never complete from the command line alone.
"""

from __future__ import annotations

from supervisor.bootstrap import bootstrap

bootstrap()

import argparse  # noqa: E402
import re  # noqa: E402
import sys  # noqa: E402
from types import SimpleNamespace  # noqa: E402
from typing import TYPE_CHECKING  # noqa: E402

from supervisor.core.errors import SupervisorError  # noqa: E402
from supervisor.tasks.model import CLASSES, LEVELS, OWNER_ROLES  # noqa: E402

if TYPE_CHECKING:
    from supervisor.tasks.service import TaskService


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


def _actor(args: argparse.Namespace) -> SimpleNamespace:
    return SimpleNamespace(
        user_id=args.by, kind="user", roles=frozenset({args.role}), auth_method="cli"
    )


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="python -m supervisor.tasks", description=__doc__)
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("list")
    p.add_argument("--agent", default="")
    p.add_argument("--stage", default="")
    p.add_argument("--status", default="")
    p.add_argument("--required", default="")
    p = sub.add_parser("plan")
    p.add_argument("--class", dest="d33_class", choices=CLASSES, required=True)
    p.add_argument("--band", choices=LEVELS, required=True)
    for name in ("generate", "done", "waive"):
        p = sub.add_parser(name)
        if name == "generate":
            p.add_argument("--agent", required=True)
        else:
            p.add_argument("task_id")
        p.add_argument("--by", required=True, type=_by, help="who does this (your user id)")
        p.add_argument("--role", choices=OWNER_ROLES, default="owner")
        if name == "done":
            p.add_argument("--evidence-ref", default=None)
        if name == "waive":
            p.add_argument("--reason", required=True)
    args = ap.parse_args(argv)

    from supervisor.config import load_settings
    from supervisor.tasks.service import TaskService

    try:
        settings = load_settings()
        if args.cmd == "plan":  # needs the template file only: no store, no flag
            return _do(args, TaskService(None, None, None, settings))
        if not settings.controls_enabled:
            _say("[SKIP] task list is off (CONTROLS_ENABLED=1 turns it on)")
            return 0
        if args.cmd in ("generate", "done", "waive"):
            from supervisor.monitors.jobctx import standalone

            with standalone(settings) as (_, _adapters, ctx):
                svc = TaskService(ctx.state, ctx.tables, ctx.clock, settings, evidence=ctx.evidence)
                return _do(args, svc)
        from supervisor.adapters.factory import build_adapters
        from supervisor.jobs import bootstrap_schema

        adapters = build_adapters(settings)
        try:
            if adapters.executor.dialect == "sqlite":
                bootstrap_schema.run(settings, adapters)
            return _do(args, TaskService.from_adapters(adapters))
        finally:
            adapters.close()
    except (SupervisorError, OSError) as exc:
        _say(f"[FAIL] {exc}")
        return 1


def _do(args: argparse.Namespace, svc: TaskService) -> int:
    if args.cmd == "list":
        rows = svc.list_tasks(
            {
                "agent": args.agent,
                "stage": args.stage,
                "status": args.status,
                "required": args.required,
            }
        )
        _say(f"{'AGENT':16} {'STAGE':13} {'TASK':16} {'REQ':3} {'STATUS':11} {'DUE':10} TITLE")
        for r in rows:
            _say(
                f"{r['agent_id']:16} {r['stage']:13} {r['template_id']:16} "
                f"{'yes' if r['required'] else 'no':3} {r['status']:11} "
                f"{(r['due_at'] or '-')[:10]:10} {_cut(r['title'], 44)}"
            )
        _say(f"[OK] {len(rows)} task(s)")
    elif args.cmd == "plan":
        p = svc.preview(args.d33_class, args.band)
        _say(
            f"class {p['d33_class']}, band {p['band']} -> level {p['level']} "
            f"({p['total_n']} tasks, {p['required_n']} required; ILLUSTRATIVE)"
        )
        for stage in p["stages"]:
            ids = ", ".join(f"{t['id']}{'*' if t['required'] else ''}" for t in p["tasks"][stage])
            _say(f"  {stage:13} {ids}")
        _say("[OK] * = required (blocks the lifecycle move and the launch gate)")
    elif args.cmd == "generate":
        out = svc.generate(args.agent, _actor(args))
        _audit(svc, args.by, "tasks.edit", "supervisor.tasks generate", "task", "generate")
        _say(
            f"[OK] {out['agent_id']}: stage {out['stage']}, class {out['d33_class']}, band "
            f"{out['band']} ({out['band_source']}), level {out['level']}; "
            f"created={out['created_n']} made_required={out['made_required']}"
        )
    elif args.cmd == "done":
        out = svc.done(args.task_id, _actor(args), args.evidence_ref)
        _audit(svc, args.by, "tasks.edit", "supervisor.tasks done", "task", "done")
        _say(f"[OK] {out['task_id']} {out['template_id']} is {out['status']}")
        stage = svc.current_stage(out["agent_id"])
        _say(f"     agent {out['agent_id']} is in stage {stage}")
    else:
        out = svc.request_waive(args.task_id, _actor(args), args.reason)
        _audit(svc, args.by, "tasks.edit", "supervisor.tasks waive", "task", "waive_request")
        _say(
            f"[OK] {out['task_id']}: waiver asked by {args.by}; a different approver or admin "
            "must answer at POST /v1/tasks/<id>/waive/approve"
        )
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))

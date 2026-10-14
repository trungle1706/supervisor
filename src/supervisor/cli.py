"""Command line entry point: python -m supervisor.cli <command>.

ASCII output only. Never use console-script stubs (AppLocker blocks them).
"""

from __future__ import annotations

from supervisor.bootstrap import bootstrap

bootstrap()

import argparse  # noqa: E402
import sys  # noqa: E402

from supervisor.config import REPO_ROOT  # noqa: E402
from supervisor.core.errors import SupervisorError  # noqa: E402

EXPORT_REQS_ARGV = [
    "uv",
    "export",
    "--frozen",
    "--no-dev",
    "--extra",
    "databricks",
    "--no-hashes",
    "--no-emit-project",
    "--no-header",
]


def cmd_serve(args: argparse.Namespace) -> int:
    import uvicorn

    from supervisor.config import load_settings

    settings = load_settings()
    host = args.host or settings.host
    port = args.port or settings.port
    print(f"[OK] serving on http://{host}:{port} (mode={settings.supervisor_mode})")
    uvicorn.run("supervisor.app:app", host=host, port=port, log_level="info")
    return 0


def cmd_preflight(_: argparse.Namespace) -> int:
    from supervisor.preflight import main

    return main()


def cmd_demo(args: argparse.Namespace) -> int:
    """WP11 demo harness: seed, 4 incidents, tamper test, reset (supervisor.demo.runbook)."""
    from supervisor.demo import runbook

    return runbook.main(list(getattr(args, "demo_args", None) or []))


def cmd_verify(args: argparse.Namespace) -> int:
    from supervisor.evidence import verify

    argv = [args.export_dir]
    if args.pubkey:
        argv += ["--pubkey", args.pubkey]
    if args.anchors:
        argv += ["--anchors", args.anchors]
    if args.strict:
        argv.append("--strict")
    if args.partial:
        argv.append("--partial")
    return int(verify.main(argv))


def cmd_export_reqs(_: argparse.Namespace) -> int:
    from supervisor import sandbox

    out = REPO_ROOT / "requirements.txt"
    result = sandbox.run([*EXPORT_REQS_ARGV, "-o", str(out)], cwd=REPO_ROOT, timeout_s=300)
    if not result.ok:
        print("[FAIL] uv export failed:")
        print(result.stderr.encode("ascii", "backslashreplace").decode("ascii"))
        return 1
    print(f"[OK] wrote {out}")
    return 0


def cmd_release(args: argparse.Namespace) -> int:
    """WP11 hand-off zip: archive of HEAD + requirements + uv.toml + HANDOFF + leak sweep."""
    from supervisor import release

    return release.main(list(getattr(args, "release_args", None) or []))


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="python -m supervisor.cli", description="Supervisor CLI")
    sub = p.add_subparsers(dest="command", required=True)
    s = sub.add_parser("serve", help="run the web app")
    s.add_argument("--host", default=None)
    s.add_argument("--port", type=int, default=None)
    s.set_defaults(func=cmd_serve)
    sub.add_parser("preflight", help="check config and environment").set_defaults(
        func=cmd_preflight
    )
    # demo and release parse their own options (main() hands them the rest of argv).
    sub.add_parser(
        "demo", help="demo harness: seed, inject 1-4, tamper, reset, serve (WP11)"
    ).set_defaults(func=cmd_demo)
    v = sub.add_parser("verify", help="verify an evidence export offline (WP6)")
    v.add_argument("export_dir", nargs="?", default=".")
    v.add_argument("--pubkey", default=None, help="pinned notary public key (PEM)")
    v.add_argument("--anchors", default=None, help="directory of anchor documents")
    v.add_argument("--strict", action="store_true", help="fail on entries not yet sealed")
    v.add_argument("--partial", action="store_true", help="accept a lane (partial) export")
    v.set_defaults(func=cmd_verify)
    sub.add_parser("export-reqs", help="write requirements.txt from uv.lock").set_defaults(
        func=cmd_export_reqs
    )
    sub.add_parser("release", help="build the hand-off zip (WP11)").set_defaults(func=cmd_release)
    return p


PASSTHROUGH = {"demo": "demo_args", "release": "release_args"}  # own argparse inside


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if argv and argv[0] in PASSTHROUGH:
        # demo and release parse their own options (any order), so hand them the rest.
        args = argparse.Namespace(command=argv[0], **{PASSTHROUGH[argv[0]]: argv[1:]})
        args.func = cmd_demo if argv[0] == "demo" else cmd_release
    else:
        args = build_parser().parse_args(argv)
    try:
        return int(args.func(args))
    except SupervisorError as exc:
        print(f"[FAIL] {exc}".encode("ascii", "backslashreplace").decode("ascii"))
        return 1


if __name__ == "__main__":
    sys.exit(main())

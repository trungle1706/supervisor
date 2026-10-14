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


def cmd_demo(_: argparse.Namespace) -> int:
    print("[SKIP] demo is not built yet (WP11). It will run, with no network:")
    for step in (
        "1. seed synthetic Vietnamese data and register 3 agents",
        "2. inject 4 incidents; the gateway blocks or pauses each with a real rule",
        "3. judges add advisory verdicts and open cases",
        "4. tamper with one evidence row in an export; verify reports the break",
        "5. reset to the snapshot; replay mode as fallback",
    ):
        print(f"       {step}")
    return 0


def cmd_verify(args: argparse.Namespace) -> int:
    from supervisor.evidence import verify

    argv = [args.export_dir]
    if args.pubkey:
        argv += ["--pubkey", args.pubkey]
    if args.anchors:
        argv += ["--anchors", args.anchors]
    if args.strict:
        argv.append("--strict")
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


def cmd_release(_: argparse.Namespace) -> int:
    print("[FAIL] release is not built yet (WP11): git archive + uv.toml + leak sweep")
    return 2


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
    sub.add_parser("demo", help="run the demo (WP11)").set_defaults(func=cmd_demo)
    v = sub.add_parser("verify", help="verify an evidence export offline (WP6)")
    v.add_argument("export_dir", nargs="?", default=".")
    v.add_argument("--pubkey", default=None, help="pinned notary public key (PEM)")
    v.add_argument("--anchors", default=None, help="directory of anchor documents")
    v.add_argument("--strict", action="store_true", help="fail on entries not yet sealed")
    v.set_defaults(func=cmd_verify)
    sub.add_parser("export-reqs", help="write requirements.txt from uv.lock").set_defaults(
        func=cmd_export_reqs
    )
    sub.add_parser("release", help="build the hand-off zip (WP11)").set_defaults(func=cmd_release)
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        return int(args.func(args))
    except SupervisorError as exc:
        print(f"[FAIL] {exc}".encode("ascii", "backslashreplace").decode("ascii"))
        return 1


if __name__ == "__main__":
    sys.exit(main())

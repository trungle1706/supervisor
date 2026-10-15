"""CLI: ``python -m supervisor.onboard --target <agent folder> --out <folder>``.

Retire (WP19): ``python -m supervisor.onboard --retire <agent_id> --principal <admin>
--reason "..." --out <folder>`` (``--target`` is a folder, so retire has its own flag).

ASCII output only ([OK] / [FAIL]). Exit 0 when every stage ran and the artefacts were
written (the launch decision GO or NO-GO is in the report), 1 on an error.
"""

from __future__ import annotations

from supervisor.bootstrap import bootstrap

bootstrap()

import argparse  # noqa: E402
import sys  # noqa: E402
from collections.abc import Sequence  # noqa: E402


def _ascii(text: str) -> str:
    return text.encode("ascii", "replace").decode("ascii")


def _retire(args: argparse.Namespace) -> int:
    from supervisor.config import load_settings
    from supervisor.core.errors import SupervisorError
    from supervisor.onboard.operate import retire
    from supervisor.wiring import build_runtime

    def echo(line: str) -> None:
        print(_ascii(line))  # noqa: T201

    if not (args.principal and args.reason and args.out):
        echo("[FAIL] --retire needs --principal, --reason and --out")
        return 1
    try:
        runtime = build_runtime(load_settings())
        try:
            res = retire(
                runtime, args.retire, principal=args.principal, reason=args.reason, out_dir=args.out
            )
        finally:
            runtime.close()
    except (SupervisorError, OSError, ValueError) as exc:
        echo(f"[FAIL] retire stopped: {type(exc).__name__}: {exc}")
        return 1
    except Exception as exc:  # noqa: BLE001 - CLI prints [FAIL], never a traceback
        echo(f"[FAIL] retire stopped by an internal error: {type(exc).__name__}")
        return 1
    echo(f"[OK] {res.agent_id} is RETIRED; {len(res.cases_closed)} case(s) closed")
    echo(f"[OK] wrote {res.note_path}")
    echo(f"[{'OK' if res.verify_ok else 'FAIL'}] audit pack {res.pack_path}")
    return 0 if res.verify_ok else 1


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m supervisor.onboard")
    parser.add_argument("--target", help="agent folder (inside a repository)")
    parser.add_argument("--out", help="output folder for the artefacts")
    parser.add_argument("--retire", metavar="AGENT_ID", help="retire this agent (stage 7)")
    parser.add_argument("--principal", help="with --retire: the admin who retires the agent")
    parser.add_argument("--reason", help="with --retire: why the agent is retired")
    parser.add_argument("--work-dir", help="folder for the clone and the sandbox")
    parser.add_argument("--workspace-fixture", help="JSON workspace fixture (offline)")
    parser.add_argument(
        "--mock-llm", action="store_true", help="use the mock model (deterministic profile)"
    )
    args = parser.parse_args(argv)
    if args.retire:
        return _retire(args)
    if not args.target or not args.out:
        parser.error("--target and --out are required (or use --retire AGENT_ID)")

    from supervisor.adapters.llm.mock import MockChat
    from supervisor.adapters.workspace import FixtureWorkspaceReader
    from supervisor.core.errors import SupervisorError
    from supervisor.onboard.run import run_onboarding

    def echo(line: str) -> None:
        print(_ascii(line))  # noqa: T201

    try:
        res = run_onboarding(
            args.target,
            args.out,
            work_dir=args.work_dir,
            chat=MockChat(model_id="mock-onboarding-v1") if args.mock_llm else None,
            workspace=FixtureWorkspaceReader.from_file(args.workspace_fixture)
            if args.workspace_fixture
            else None,
            echo=echo,
        )
    except (SupervisorError, OSError, ValueError) as exc:
        echo(f"[FAIL] onboarding stopped: {type(exc).__name__}: {exc}")
        return 1
    except Exception as exc:  # noqa: BLE001 - CLI prints [FAIL], never a traceback
        echo(f"[FAIL] onboarding stopped by an internal error: {type(exc).__name__}")
        return 1
    for name in sorted(res.artefacts):
        echo(f"[OK] wrote {res.artefacts[name]}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

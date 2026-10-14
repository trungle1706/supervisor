"""CLI: ``python -m supervisor.onboard --target <agent folder> --out <folder>``.

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


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m supervisor.onboard")
    parser.add_argument("--target", required=True, help="agent folder (inside a git repo)")
    parser.add_argument("--out", required=True, help="output folder for the artefacts")
    parser.add_argument("--work-dir", help="folder for the clone and the sandbox")
    parser.add_argument("--workspace-fixture", help="JSON workspace fixture (offline)")
    parser.add_argument(
        "--mock-llm", action="store_true", help="use the mock model (deterministic profile)"
    )
    args = parser.parse_args(argv)

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

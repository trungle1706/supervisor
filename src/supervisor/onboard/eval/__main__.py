"""CLI: ``python -m supervisor.onboard.eval --corpus ... --labels ... --report <dir>``.

ASCII output only. Exit 0 on success; 1 when ``--check-labels`` finds problems or
``--fail-on-gates`` is set and a gate fails; 2 on bad input.
"""

from __future__ import annotations

from supervisor.bootstrap import bootstrap

bootstrap()

import argparse  # noqa: E402
import sys  # noqa: E402
from collections.abc import Sequence  # noqa: E402

import yaml  # noqa: E402

from supervisor.onboard.eval.labels import check_labels, load_labels  # noqa: E402
from supervisor.onboard.eval.report import ascii_safe, summary_lines, write_report  # noqa: E402
from supervisor.onboard.eval.runner import run_eval  # noqa: E402


def _echo(line: str) -> None:
    print(ascii_safe(line))  # noqa: T201


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m supervisor.onboard.eval")
    parser.add_argument("--corpus", required=True, help="folder with one sub-folder per repo")
    parser.add_argument("--labels", required=True, help="labels.yaml")
    parser.add_argument("--report", help="output folder for report.json and report.md")
    parser.add_argument("--check-labels", action="store_true", help="only check the labels")
    parser.add_argument("--fail-on-gates", action="store_true", help="exit 1 if a gate fails")
    parser.add_argument("--repo", action="append", metavar="NAME", help="only this repo")
    try:
        args = parser.parse_args(argv)
    except SystemExit as exc:
        return 2 if exc.code else 0
    try:
        if args.check_labels:
            problems = check_labels(args.corpus, load_labels(args.labels))
            for p in problems:
                _echo(f"[FAIL] {p}")
            if problems:
                return 1
            _echo("[OK] labels match the corpus")
            return 0
        if not args.report:
            _echo("[FAIL] --report is required unless --check-labels is set")
            return 2
        res = run_eval(args.corpus, args.labels, args.repo)
        paths = write_report(res, args.report)
    except (OSError, ValueError, yaml.YAMLError) as exc:
        _echo(f"[FAIL] eval stopped: {type(exc).__name__}: {exc}")
        return 2
    for line in summary_lines(res):
        _echo(line)
    for key in sorted(paths):
        _echo(f"[OK] wrote {paths[key]}")
    if args.fail_on_gates and not res.all_gates_ok:
        _echo("[FAIL] at least one gate failed")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())

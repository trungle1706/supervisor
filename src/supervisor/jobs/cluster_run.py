"""Run a Databricks source notebook on the shared interactive cluster (optional, heavy jobs).

Uses the Command Execution API (execution contexts), not Jobs: the bank's shared cluster
refuses job workloads. Needs the ``databricks`` extra, a CLI OAuth profile and
``DATABRICKS_CLUSTER_NAME`` (or ``DATABRICKS_CLUSTER_ID``). Off unless you run it.

Run (cmd):
    uv run python -m supervisor.jobs.cluster_run notebooks\\bootstrap_and_smoke.py ^
        --param CATALOG=my_catalog --param SCHEMA=my_schema

Parameters override the defaults in the notebook's ``# SUPERVISOR-PARAMS`` cell (no widgets).
The result is
the notebook's last ``SUPERVISOR-EXIT-JSON:`` line. Exit code 0 when every cell passed.
Also callable in-process: ``run(settings, path, params)``.
"""

from __future__ import annotations

from supervisor.bootstrap import bootstrap

bootstrap()

import argparse  # noqa: E402
import json  # noqa: E402
import sys  # noqa: E402
from collections.abc import Mapping  # noqa: E402
from pathlib import Path  # noqa: E402
from typing import Any  # noqa: E402

from supervisor.config import Settings, load_settings  # noqa: E402
from supervisor.core.errors import SupervisorError  # noqa: E402
from supervisor.databricks.command_exec import CommandRunner, RunResult  # noqa: E402
from supervisor.databricks.notebook import split_cells, with_params  # noqa: E402


def parse_param(text: str) -> tuple[str, Any]:
    if "=" not in text:
        raise argparse.ArgumentTypeError(f"--param needs NAME=VALUE, got {text!r}")
    key, _, raw = text.partition("=")
    value: Any = raw
    if raw.lower() in ("true", "false"):
        value = raw.lower() == "true"
    elif raw.lstrip("-").isdigit():
        value = int(raw)
    return key.strip(), value


def run(
    settings: Settings,
    notebook: Path,
    params: Mapping[str, Any] | None = None,
    *,
    runner: CommandRunner | None = None,
) -> RunResult:
    cells = with_params(split_cells(notebook.read_text(encoding="utf-8")), params)
    runner = runner or CommandRunner.from_settings(settings)
    return runner.run(cells)


def _say(text: str) -> None:
    print(text.encode("ascii", "backslashreplace").decode("ascii"))


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="python -m supervisor.jobs.cluster_run")
    ap.add_argument("notebook", help="Databricks source-format notebook (.py)")
    ap.add_argument("--param", action="append", type=parse_param, default=[])
    ap.add_argument("--cluster-name", default=None)
    ap.add_argument("--cluster-id", default=None)
    ap.add_argument("--deadline-s", type=int, default=None)
    args = ap.parse_args(argv)
    overrides: dict[str, Any] = {}
    if args.cluster_name:
        overrides["databricks_cluster_name"] = args.cluster_name
    if args.cluster_id:
        overrides["databricks_cluster_id"] = args.cluster_id
    if args.deadline_s:
        overrides["databricks_command_deadline_s"] = args.deadline_s
    try:
        settings = load_settings(**overrides)
        result = run(settings, Path(args.notebook).resolve(), dict(args.param))
    except SupervisorError as exc:
        _say(f"[FAIL] {exc}")
        return 1
    for cell in result.cells:
        mark = "OK" if cell.ok else "FAIL"
        _say(f"[{mark}] cell {cell.index} ({cell.status})")
        if not cell.ok:
            _say(cell.error)
    if result.error:
        _say(f"[FAIL] {result.error}")
    if result.cells and not result.context_destroyed:
        _say("[WARN] execution context was not confirmed destroyed (it times out on its own)")
    if result.exit is not None:
        _say("SUPERVISOR-EXIT-JSON: " + json.dumps(result.exit, sort_keys=True))
    _say(f"[{'OK' if result.ok else 'FAIL'}] {len(result.cells)} cells on {result.cluster_id}")
    return 0 if result.ok else 1


if __name__ == "__main__":
    sys.exit(main())

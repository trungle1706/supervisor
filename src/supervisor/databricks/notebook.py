"""Databricks source-format notebooks: split into cells, inline parameters, keep DDL current.

Format (what the workspace exports and imports)::

    # Databricks notebook source
    <cell 0>
    # COMMAND ----------
    <cell 1>

``# MAGIC %md`` cells are documentation and are skipped by the runner. A cell that holds
the marker ``# SUPERVISOR-PARAMS`` gets :func:`command_exec.params_cell` appended when
parameters are given, so they override its defaults (no widgets in command mode).

``notebooks/bootstrap_and_smoke.py`` embeds the Databricks DDL generated from
``schema/model.yaml`` between two marker lines, so the notebook works when it is pasted
into the workspace on its own. Regenerate: ``uv run python -m supervisor.databricks.notebook``;
a test checks it is current.
"""

from __future__ import annotations

import argparse
import sys
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from supervisor.config import REPO_ROOT
from supervisor.core.schema import SchemaModel, databricks_statements, load_model
from supervisor.databricks.command_exec import CommandExecError, params_cell

HEADER = "# Databricks notebook source"
SEPARATOR = "# COMMAND ----------"
PARAMS_MARKER = "# SUPERVISOR-PARAMS"
DDL_BEGIN = "# GENERATED DDL BEGIN"
DDL_END = "# GENERATED DDL END"
SMOKE_NOTEBOOK = REPO_ROOT / "notebooks" / "bootstrap_and_smoke.py"


def split_cells(source: str) -> list[str]:
    """Code cells of a source-format notebook (markdown cells dropped)."""
    lines = source.splitlines()
    if not lines or lines[0].strip() != HEADER:
        raise CommandExecError(f"not a Databricks source notebook (first line must be {HEADER!r})")
    cells: list[list[str]] = [[]]
    for line in lines[1:]:
        if line.strip() == SEPARATOR:
            cells.append([])
        else:
            cells[-1].append(line)
    out = []
    for cell in cells:
        text = "\n".join(cell).strip("\n")
        if not text.strip():
            continue
        first = text.lstrip().splitlines()[0]
        if first.startswith("# MAGIC %md"):
            continue
        if first.startswith("# MAGIC"):
            raise CommandExecError(f"magic cell not supported by the runner: {first[:60]}")
        out.append(text + "\n")
    return out


def with_params(cells: list[str], params: Mapping[str, Any] | None) -> list[str]:
    """Append inline parameters to the ``# SUPERVISOR-PARAMS`` cell (they override its defaults)."""
    if not params:
        return cells
    idx = [i for i, c in enumerate(cells) if PARAMS_MARKER in c]
    if len(idx) != 1:
        raise CommandExecError(
            f"notebook needs exactly one {PARAMS_MARKER} cell to take parameters"
        )
    out = list(cells)
    out[idx[0]] = (
        cells[idx[0]].rstrip("\n") + "\n# inline parameters (override the defaults above)\n"
    )
    out[idx[0]] += params_cell(params)
    return out


def ddl_block(model: SchemaModel | None = None) -> str:
    """The generated ``DDL = [...]`` block (catalog/schema as ${catalog}/${schema})."""
    stmts = databricks_statements(model or load_model())
    body = ",\n".join(f"    {s!r}" for s in stmts)
    return (
        f"{DDL_BEGIN} (uv run python -m supervisor.databricks.notebook; do not edit)\n"
        f"DDL = [\n{body},\n]\n"
        f"{DDL_END}"
    )


def render(text: str, model: SchemaModel | None = None) -> str:
    start = text.find(DDL_BEGIN)
    end = text.find(DDL_END)
    if start < 0 or end < start:
        raise CommandExecError("notebook has no generated DDL markers")
    return text[:start] + ddl_block(model) + text[end + len(DDL_END) :]


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="python -m supervisor.databricks.notebook")
    ap.add_argument("--check", action="store_true", help="exit 1 if the notebook is stale")
    ap.add_argument("path", nargs="?", default=str(SMOKE_NOTEBOOK))
    args = ap.parse_args(argv)
    path = Path(args.path).resolve()
    text = path.read_text(encoding="utf-8")
    new = render(text)
    if args.check:
        if new != text:
            print(f"[FAIL] {path} is stale: run uv run python -m supervisor.databricks.notebook")  # noqa: T201
            return 1
        print(f"[OK] {path} DDL is current")  # noqa: T201
        return 0
    if new != text:
        path.write_text(new, encoding="utf-8", newline="\n")
    print(f"[OK] wrote {path}")  # noqa: T201
    return 0


if __name__ == "__main__":
    sys.exit(main())

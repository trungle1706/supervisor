"""Create every table from schema/model.yaml in the configured backend. Idempotent.

Run: uv run python -m supervisor.jobs.bootstrap_schema [--print]
Also callable in-process: ``run(settings)``.
"""

from __future__ import annotations

from supervisor.bootstrap import bootstrap

bootstrap()

import argparse  # noqa: E402
import sys  # noqa: E402

from supervisor.adapters.factory import Adapters, build_adapters  # noqa: E402
from supervisor.config import Settings, load_settings  # noqa: E402
from supervisor.core.errors import SupervisorError  # noqa: E402
from supervisor.core.schema import (  # noqa: E402
    SchemaModel,
    databricks_statements,
    sqlite_statements,
)


def statements_for(adapters: Adapters) -> list[str]:
    x = adapters.executor
    model: SchemaModel = adapters.model
    prefix = adapters.settings.table_prefix
    if x.dialect == "sqlite":
        return sqlite_statements(model, prefix=prefix)
    return databricks_statements(
        model,
        catalog=str(adapters.settings.databricks_catalog),
        schema=str(adapters.settings.databricks_schema),
        prefix=prefix,
    )


def run(settings: Settings | None = None, adapters: Adapters | None = None) -> dict[str, int]:
    """Apply DDL and record the model version. Safe to run many times."""
    settings = settings or load_settings()
    adapters = adapters or build_adapters(settings)
    stmts = statements_for(adapters)
    adapters.executor.apply_ddl(stmts)
    model = adapters.model
    recorded = adapters.state.get("schema_version", {"version": model.version})
    if recorded is None:
        adapters.state.insert(
            "schema_version",
            {
                "version": model.version,
                "applied_at": adapters.clock.now(),
                "model_hash": model.source_hash,
            },
        )
    elif recorded["model_hash"] != model.source_hash:
        adapters.state.update(
            "schema_version",
            {"version": model.version},
            {"applied_at": adapters.clock.now(), "model_hash": model.source_hash},
            expected_version=recorded["row_version"],
        )
    return {"statements": len(stmts), "tables": len(model.tables)}


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="python -m supervisor.jobs.bootstrap_schema")
    ap.add_argument("--print", action="store_true", help="print the DDL; do not run it")
    args = ap.parse_args(argv)
    try:
        settings = load_settings()
        adapters = build_adapters(settings)
        if args.print:
            for s in statements_for(adapters):
                print(s + ";\n")
            return 0
        target = adapters.executor.describe()
        result = run(settings, adapters)
    except SupervisorError as exc:
        print(f"[FAIL] {exc}".encode("ascii", "backslashreplace").decode("ascii"))
        return 1
    line = f"[OK] schema applied: {result['tables']} tables, {result['statements']} statements"
    print(f"{line} on {target}".encode("ascii", "backslashreplace").decode("ascii"))
    return 0


if __name__ == "__main__":
    sys.exit(main())

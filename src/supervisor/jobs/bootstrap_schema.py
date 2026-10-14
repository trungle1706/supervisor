"""Create every table from schema/model.yaml in the configured backend, then migrate.

Step 1: ``CREATE TABLE IF NOT EXISTS`` for every table (new tables get everything).
Step 2: additive migration of existing tables (``supervisor.core.schema_diff``): missing
columns are added, Delta append-only and retention properties are set. Never drops.
Idempotent: a second run applies nothing.

Run: uv run python -m supervisor.jobs.bootstrap_schema [--print | --plan]
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
    load_model,
    sqlite_statements,
)
from supervisor.core.schema_diff import MigrationPlan, migrate  # noqa: E402


def statements_for(adapters: Adapters) -> list[str]:
    return statements_for_settings(adapters.settings, adapters.executor.dialect, adapters.model)


def statements_for_settings(
    settings: Settings, dialect: str, model: SchemaModel | None = None
) -> list[str]:
    model = model or load_model()
    if dialect == "sqlite":
        return sqlite_statements(model, prefix=settings.table_prefix)
    return databricks_statements(
        model,
        catalog=str(settings.databricks_catalog),
        schema=str(settings.databricks_schema),
        prefix=settings.table_prefix,
        retention_days=settings.evidence_retention_days,
    )


def run(
    settings: Settings | None = None,
    adapters: Adapters | None = None,
    *,
    plan_out: list[MigrationPlan] | None = None,
) -> dict[str, int]:
    """Apply DDL, migrate existing tables, record the model version. Safe to run many times.

    ``plan_out`` (optional) receives the migration plan (statements and warnings)."""
    settings = settings or load_settings()
    adapters = adapters or build_adapters(settings)
    stmts = statements_for(adapters)
    adapters.executor.apply_ddl(stmts)
    model = adapters.model
    plan = migrate(adapters.executor, model, settings.evidence_retention_days)
    if plan_out is not None:
        plan_out.append(plan)
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
    return {
        "statements": len(stmts) + len(plan.statements),
        "tables": len(model.tables),
        "added_columns": plan.added_columns,
        "properties_set": plan.properties_set,
        "warnings": len(plan.warnings),
    }


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="python -m supervisor.jobs.bootstrap_schema")
    ap.add_argument("--print", action="store_true", help="print the DDL; do not run it")
    ap.add_argument(
        "--plan",
        action="store_true",
        help="connect, read the live schema and print the migration; change nothing",
    )
    args = ap.parse_args(argv)
    try:
        settings = load_settings()
        if args.print:  # no connection, no files created
            dialect = "sqlite" if settings.effective_sql_backend == "sqlite" else "databricks"
            for stmt in statements_for_settings(settings, dialect):
                print((stmt + ";\n").encode("ascii", "backslashreplace").decode("ascii"))
            return 0
        adapters = build_adapters(settings)
        target = adapters.executor.describe()
        if args.plan:
            plan = migrate(
                adapters.executor,
                adapters.model,
                settings.evidence_retention_days,
                dry_run=True,
            )
            for stmt in plan.statements:
                _say(stmt + ";")
            for w in plan.warnings:
                _say(f"[WARN] {w}")
            _say(f"[OK] plan: {len(plan.statements)} statements on {target} (nothing applied)")
            return 0
        plans: list[MigrationPlan] = []
        result = run(settings, adapters, plan_out=plans)
    except SupervisorError as exc:
        _say(f"[FAIL] {exc}")
        return 1
    for w in plans[0].warnings if plans else []:
        _say(f"[WARN] {w}")
    _say(
        f"[OK] schema applied: {result['tables']} tables, {result['statements']} statements, "
        f"{result['added_columns']} columns added, {result['properties_set']} tables with "
        f"properties set on {target}"
    )
    return 0


def _say(text: str) -> None:
    print(text.encode("ascii", "backslashreplace").decode("ascii"))


if __name__ == "__main__":
    sys.exit(main())

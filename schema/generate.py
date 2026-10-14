"""Generate schema/ddl/*.sql from schema/model.yaml.

Usage:  uv run python -m schema.generate          (write files)
        uv run python -m schema.generate --check  (exit 1 if files are stale)
"""

from __future__ import annotations

import argparse
import sys

from supervisor.core.schema import (
    DDL_DIR,
    MODEL_PATH,
    parse_model,
    render_databricks,
    render_sqlite,
)


def outputs() -> dict[str, str]:
    model = parse_model(MODEL_PATH.read_text(encoding="utf-8"))
    return {"sqlite.sql": render_sqlite(model), "databricks.sql": render_databricks(model)}


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="python -m schema.generate")
    ap.add_argument("--check", action="store_true", help="fail if committed DDL is stale")
    args = ap.parse_args(argv)
    stale = []
    for name, text in outputs().items():
        path = DDL_DIR / name
        current = path.read_bytes().decode("utf-8") if path.exists() else None
        if args.check:
            if current != text:
                stale.append(name)
            continue
        DDL_DIR.mkdir(parents=True, exist_ok=True)
        path.write_bytes(text.encode("utf-8"))  # LF line endings on every OS
        print(f"[OK] wrote {path}")
    if stale:
        print("[FAIL] stale DDL: " + ", ".join(stale) + " -- run: uv run python -m schema.generate")
        return 1
    if args.check:
        print("[OK] DDL is current")
    return 0


if __name__ == "__main__":
    sys.exit(main())

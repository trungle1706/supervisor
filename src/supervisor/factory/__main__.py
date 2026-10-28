"""``python -m supervisor.factory``: validate a file against a factory schema, print a JSON schema.

    python -m supervisor.factory validate <file> [--schema NAME]
    python -m supervisor.factory schema <name>

Exit 0 when valid, 1 on any error. Output is ASCII (``[OK]`` / ``[FAIL]``); an error line names the
field. A bad file never produces a traceback.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

import yaml
from pydantic import ValidationError

from supervisor.factory import registry
from supervisor.factory.schemas import MODELS


def detect(doc: Any) -> str | None:
    """Pick the schema of a document from its keys."""
    if not isinstance(doc, dict):
        return None
    if "harness" in doc or "schema_version" in doc:
        return "agent_definition_v1"
    if "report_id" in doc or "findings" in doc:
        return "assessment_report_v1"
    if "facts" in doc or "version" in doc:
        return "facts_v1"
    return None


def _loc(parts: tuple[Any, ...]) -> str:
    out = ""
    for p in parts:
        out += f"[{p}]" if isinstance(p, int) else (f".{p}" if out else str(p))
    return out


def format_errors(exc: ValidationError) -> list[str]:
    lines = []
    for e in exc.errors(include_url=False, include_input=False):
        msg = str(e["msg"]).removeprefix("Value error, ")
        loc = _loc(tuple(e["loc"]))
        lines.append(f"{loc}: {msg}" if loc else msg)
    return lines


def _out(text: str) -> None:
    sys.stdout.write(text.encode("ascii", "replace").decode("ascii") + "\n")


def validate_file(path: Path, schema: str | None) -> tuple[str, list[str]]:
    """Returns ``(schema name, error lines)``; an empty list means valid."""
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        return schema or "?", [f"file: cannot read {path.name} ({type(exc).__name__})"]
    try:
        doc = yaml.safe_load(text)
    except yaml.YAMLError as exc:
        mark = getattr(exc, "problem_mark", None)
        where = f" at line {mark.line + 1}" if mark is not None else ""
        return schema or "?", [f"file: not valid YAML or JSON{where}"]
    name = schema or detect(doc)
    if name is None:
        return "?", ["file: cannot tell which schema it is; pass --schema NAME"]
    try:
        model = MODELS[name].model_validate(doc)
    except ValidationError as exc:
        return name, format_errors(exc)
    if name == "agent_definition_v1":
        try:
            found = registry.check_definition(model, registry.load_tools(), registry.load_groups())
        except registry.RegistryError as exc:
            return name, [f"registry: {exc}"]
        return name, [f"{field}: {msg}" for field, msg in found]
    return name, []


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m supervisor.factory")
    sub = parser.add_subparsers(dest="cmd", required=True)
    v = sub.add_parser("validate", help="validate a YAML or JSON file")
    v.add_argument("file")
    v.add_argument("--schema", choices=sorted(MODELS), default=None)
    s = sub.add_parser("schema", help="print the JSON schema")
    s.add_argument("name", choices=sorted(MODELS))
    args = parser.parse_args(argv)

    if args.cmd == "schema":
        doc = MODELS[args.name].model_json_schema()
        _out(json.dumps(doc, indent=2, sort_keys=True, ensure_ascii=True))
        return 0

    name, errors = validate_file(Path(args.file), args.schema)
    if errors:
        for line in errors:
            _out(f"[FAIL] {line}")
        _out(f"[FAIL] {args.file}: {len(errors)} error(s) against {name}")
        return 1
    _out(f"[OK] {args.file} is a valid {name}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

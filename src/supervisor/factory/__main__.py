"""``python -m supervisor.factory``: validate a file against a factory schema, print a JSON schema.

    python -m supervisor.factory validate <file> [--schema NAME]
    python -m supervisor.factory schema <name>
    python -m supervisor.factory gate <agent_id> --kind full|sample [--version V] [--n N]
        [--model fake]
    python -m supervisor.factory seed

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


def _settings() -> Any:
    from supervisor.config import load_settings

    return load_settings()


def run_seed(env: Any = None) -> int:
    """WP-F5: create the starter agents and templates the catalogue lacks, as drafts. Needs
    ``AGENT_FACTORY=1`` and ``GOVERNANCE_ENABLED=1``. Running it twice changes nothing."""
    from supervisor.core.errors import SupervisorError
    from supervisor.factory import starters, store

    runtime = None
    try:
        if env is None:
            from supervisor.console.context import build_context
            from supervisor.wiring import build_runtime

            settings = _settings()
            store.require_on(settings)
            runtime = build_runtime(settings)
            ctx = build_context(runtime)
            fstore = store.FactoryStore(ctx.state, ctx.tables, ctx.clock)
            data_dir = Path(settings.data_dir)
        else:
            store.require_on(env.settings)
            fstore, data_dir = env.store, env.data_dir
        result = starters.seed(fstore, data_dir)
    except SupervisorError as exc:
        _out(f"[FAIL] {exc}")
        return 1
    finally:
        if runtime is not None:
            runtime.close()
    for agent_id in result["created"]:
        kind = "template" if agent_id in starters.TEMPLATE_IDS else "agent"
        _out(f"[OK] created {kind} {agent_id} (draft)")
    for agent_id in result["skipped"]:
        _out(f"[SKIP] {agent_id} is already in the catalogue")
    return 0


def run_gate(args: argparse.Namespace, env: Any = None) -> int:
    """WP-F3: run the test gate for one agent version in this process (no thread). Needs
    ``AGENT_FACTORY_GATE=1`` and the gateway model. ``env`` is for tests."""
    from supervisor.core.errors import SupervisorError
    from supervisor.factory import devfake, gate

    runtime = None
    try:
        if getattr(args, "model", "gateway") == "fake" and devfake.refused(
            env.settings if env is not None else _settings()
        ):
            _out(f"[FAIL] {devfake.FAKE_REFUSED_TEXT}")
            return 1
        if env is None:
            from supervisor.wiring import build_runtime

            settings = _settings()
            gate.require_on(settings)
            runtime = build_runtime(settings)
            env = gate.GateEnv.from_runtime(runtime)
        if getattr(args, "model", "gateway") == "fake":
            from supervisor.factory import golden

            row = env.store.get(args.agent_id, args.version or None)
            if row is None:
                raise gate.GateError("not_found", f"agent {args.agent_id} does not exist")
            env.chat = devfake.ReplayChat(
                row["definition"], golden.all_gate_cases(env.data_dir, args.agent_id)
            )
            _out(f"[INFO] model: {devfake.MODEL_ID} (replays the golden fixture; development only)")
        run = gate.start(
            env,
            args.agent_id,
            args.version or "",
            args.kind,
            "cli",
            n=args.n or 0,
            background=False,
        )
    except SupervisorError as exc:
        _out(f"[FAIL] {exc}")
        return 1
    finally:
        if runtime is not None:
            runtime.close()
    l1, l2, cal = run["layer1"], run["layer2"], run["layer2"].get("calibration") or {}
    _out(f"[INFO] run {run['run_id']} {run['kind']} status {run['status']}")
    if run["status"] != "done":
        _out(f"[FAIL] the run did not finish: {l1.get('error', 'unknown')}")
        return 1
    calls = run["cost"].get("model_calls", 0)
    _out(
        f"[INFO] layer 1: {l1.get('percent', 0)} percent; "
        f"layer 2: match {l2.get('match_percent', 0)} percent, "
        f"kappa {cal.get('kappa_hundredths', '-')}; cost {calls} calls"
    )
    ok = run["verdict"] == "pass"
    _out(
        f"[{'OK' if ok else 'FAIL'}] verdict {run['verdict']}"
        + ("" if args.kind == "full" else " (a sample never promotes)")
    )
    return 0 if ok else 1


def main(argv: list[str] | None = None, gate_env: Any = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m supervisor.factory")
    sub = parser.add_subparsers(dest="cmd", required=True)
    v = sub.add_parser("validate", help="validate a YAML or JSON file")
    v.add_argument("file")
    v.add_argument("--schema", choices=sorted(MODELS), default=None)
    s = sub.add_parser("schema", help="print the JSON schema")
    s.add_argument("name", choices=sorted(MODELS))
    g = sub.add_parser("gate", help="run the test gate (AGENT_FACTORY_GATE=1)")
    g.add_argument("agent_id")
    g.add_argument("--kind", choices=["full", "sample"], default="full")
    g.add_argument("--version", default="")
    g.add_argument("--n", type=int, default=0, help="cases of a sample (default 10, at most 25)")
    g.add_argument(
        "--model",
        choices=["gateway", "fake"],
        default="gateway",
        help="fake = replay of the golden fixture, development and tests only; refused in "
        "databricks_app mode",
    )
    sub.add_parser(
        "seed", help="create the starter agents and templates as drafts (AGENT_FACTORY=1)"
    )
    args = parser.parse_args(argv)

    if args.cmd == "gate":
        return run_gate(args, gate_env)
    if args.cmd == "seed":
        return run_seed(gate_env)
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

"""CLI: python -m supervisor.advisory.compliance --profile <profile.json|product.yaml> --out DIR

Writes compliance_matrix.json / .md / .html. ASCII output only ([OK] / [FAIL]).
Exit 0 on success, 2 on bad input. Advisory only; no network except the configured LLM.

Not legal advice. Bank counsel must confirm.
"""

from __future__ import annotations

from supervisor.bootstrap import bootstrap

bootstrap()

import argparse  # noqa: E402
import os  # noqa: E402
import sys  # noqa: E402
from collections.abc import Sequence  # noqa: E402
from pathlib import Path  # noqa: E402
from typing import Any  # noqa: E402

from supervisor.config import REPO_ROOT, load_settings  # noqa: E402
from supervisor.core.errors import SupervisorError  # noqa: E402
from supervisor.regkb import DISCLAIMER  # noqa: E402
from supervisor.regkb.cli import ascii_text  # noqa: E402
from supervisor.regkb.errors import RegKBError  # noqa: E402


def _out(line: str = "") -> None:
    sys.stdout.write(ascii_text(line) + "\n")


def _internal_dir(arg: str | None) -> Path | None:
    value = arg
    if value is None:
        try:
            value = load_settings().regkb_internal_dir
        except SupervisorError:
            value = os.environ.get("REGKB_INTERNAL_DIR", "")
    value = (value or "").strip()
    if not value:
        return None
    path = Path(value).expanduser()
    return Path(os.path.abspath(path if path.is_absolute() else REPO_ROOT / path))


def _chat(mock: bool) -> Any:
    from supervisor.adapters.llm.mock import MockChat

    if mock:
        return MockChat()
    from supervisor.adapters.factory import make_chat_model

    return make_chat_model(load_settings())


def _write_template(target: str) -> int:
    from supervisor.advisory.compliance.questionnaire import template_yaml

    path = Path(target)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(template_yaml(), encoding="utf-8", newline="\n")
    _out(f"[OK] template written: {path}")
    _out(DISCLAIMER)
    return 0


def _run(args: argparse.Namespace) -> int:
    from supervisor.advisory.compliance.facts import load_profile_input
    from supervisor.advisory.compliance.matrix import build_matrix
    from supervisor.advisory.compliance.render import write_all
    from supervisor.regkb import load_kb

    if not args.profile or not args.out:
        raise ValueError("--profile and --out are required (or use --write-template FILE)")
    if args.as_of is not None:
        from datetime import date

        date.fromisoformat(args.as_of)  # ValueError on a bad date
    product = load_profile_input(
        args.profile, answers=args.answers or None, policy_files=tuple(args.policy or ())
    )
    kb = load_kb(None, _internal_dir(args.internal))
    chat = _chat(args.mock_llm)
    matrix = build_matrix(kb, product, as_of=args.as_of, chat=chat)
    paths = write_all(matrix, args.out)

    s = matrix.summary
    by = s["by_status"]
    ap = s["by_applies"]
    _out(
        f"[OK] product {matrix.header.product_id}: {matrix.header.obligations} obligations, "
        f"RegKB {matrix.header.regkb_version[:12]}"
    )
    _out(f"[OK] applies: yes {ap['yes']}, needs_answer {ap['needs_answer']}, no {ap['no']}")
    _out("[OK] status (applies=yes): " + ", ".join(f"{k} {v}" for k, v in by.items()))
    _out(f"[OK] threshold gaps: {s['threshold_gaps']}; open questions: {s['questions']}")
    _out(f"[OK] Decision 33 suggestion: {matrix.decision33.classification}")
    if matrix.header.internal_rules:
        _out("[OK] internal rules: " + ", ".join(matrix.header.internal_instruments))
    if matrix.narrative is not None:
        tag = "mock" if matrix.narrative.is_mock else "model"
        _out(f"[OK] narrative ({tag}, advisory): {matrix.narrative.model_id}")
    for key in ("json", "md", "html"):
        _out(f"[OK] wrote {paths[key]}")
    _out(DISCLAIMER)
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m supervisor.advisory.compliance",
        description="Obligations matrix for one product. Advisory only.",
    )
    parser.add_argument("--profile", help="onboard profile.json or product.yaml")
    parser.add_argument("--out", help="output folder")
    parser.add_argument("--mock-llm", action="store_true", help="force the mock narrative")
    parser.add_argument("--internal", help="folder with bank internal rule YAML files")
    parser.add_argument("--answers", help="product.yaml with answers to open questions")
    parser.add_argument("--policy", action="append", help="policy YAML file (repeatable)")
    parser.add_argument("--as-of", help="date YYYY-MM-DD (default today)")
    parser.add_argument("--write-template", metavar="FILE", help="write a commented product.yaml")
    args = parser.parse_args(argv)
    try:
        if args.write_template:
            return _write_template(args.write_template)
        return _run(args)
    except (SupervisorError, RegKBError, OSError, ValueError) as exc:
        _out(f"[FAIL] {exc}")
        return 2


if __name__ == "__main__":
    raise SystemExit(main())

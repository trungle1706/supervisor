"""CLI: ``python -m supervisor.judge.eval --model mock``.

Writes ``data/golden/eval_report.json`` and prints an ASCII table.

``--model mock``          deterministic MockJudge (report says ``mock: true``).
``--model mock-gullible`` MockJudge that obeys instructions in the data: shows that the
                          canary check and the injection floor work when a model is fooled.
``--model settings``      the judges configured in settings (JUDGE_T1_MODEL, ...).
``--split dev``           dev split only: use this while tuning prompts (never heldout).
"""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Sequence
from pathlib import Path

from supervisor.config import REPO_ROOT, load_settings
from supervisor.core.errors import SupervisorError
from supervisor.judge.eval.datasets import build_eval_sets
from supervisor.judge.eval.harness import ascii_table, run_eval
from supervisor.judge.mockjudge import MockJudgeChat
from supervisor.judge.router import JudgeRouter

DEFAULT_OUT = REPO_ROOT / "data" / "golden" / "eval_report.json"


def _router_factory(model: str):  # noqa: ANN202 - local factory
    settings = load_settings()
    if model == "settings":
        return lambda: JudgeRouter.from_settings(settings)
    gullible = model == "mock-gullible"

    def build() -> JudgeRouter:
        chats = {
            "t1": MockJudgeChat(1, model_id="mock-judge-t1-v1", gullible=gullible),
            "t2": MockJudgeChat(2, model_id="mock-judge-t2-v1", gullible=gullible),
        }
        return JudgeRouter.from_settings(settings, chats=chats)

    return build


def main(argv: Sequence[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="python -m supervisor.judge.eval")
    p.add_argument("--model", choices=("mock", "mock-gullible", "settings"), default="mock")
    p.add_argument("--runs", type=int, default=5)
    p.add_argument("--threshold-bp", type=int, default=5000)
    p.add_argument("--move-bp", type=int, default=1000)
    p.add_argument("--split", choices=("all", "heldout", "dev"), default="all")
    p.add_argument("--out", type=Path, default=DEFAULT_OUT)
    args = p.parse_args(argv)
    splits = ("heldout", "dev") if args.split == "all" else (args.split,)
    try:
        items = build_eval_sets()
        report = run_eval(
            items,
            _router_factory(args.model),
            runs=max(1, args.runs),
            threshold_bp=args.threshold_bp,
            move_bp=args.move_bp,
            splits=splits,
        )
    except SupervisorError as exc:
        print(f"[FAIL] {exc}".encode("ascii", "replace").decode("ascii"))  # noqa: T201
        return 2
    out = Path(args.out).resolve()
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(ascii_table(report))  # noqa: T201
    print(f"[OK] report written to {out}".encode("ascii", "replace").decode("ascii"))  # noqa: T201
    return 0


if __name__ == "__main__":
    sys.exit(main())

"""CLI: ``python -m supervisor.advisory.integration --target DIR --out DIR [--mock-llm]``.

ASCII output only ([OK] / [FAIL] / [SKIP]). Exit 0 when the report was written, 2 for a bad
target or output folder, 1 for an internal error. Nothing is written into the target.
"""

from __future__ import annotations

from supervisor.bootstrap import bootstrap

bootstrap()

import argparse  # noqa: E402
import sys  # noqa: E402
from collections.abc import Sequence  # noqa: E402
from pathlib import Path  # noqa: E402


def _ascii(text: str) -> str:
    return text.encode("ascii", "replace").decode("ascii")


def _say(line: str) -> None:
    print(_ascii(line))  # noqa: T201


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m supervisor.advisory.integration")
    parser.add_argument("--target", required=True, help="repository folder to read")
    parser.add_argument("--out", required=True, help="output folder (outside the target)")
    parser.add_argument("--mock-llm", action="store_true", help="use the mock model")
    args = parser.parse_args(argv)

    from supervisor.adapters.llm.mock import MockChat
    from supervisor.adapters.repo import RepoReadError
    from supervisor.advisory.integration.advise import advise
    from supervisor.advisory.integration.render import write_outputs
    from supervisor.core.errors import SupervisorError

    target = Path(args.target)
    if not target.is_dir():
        _say(f"[FAIL] target folder does not exist: {target}")
        return 2
    try:
        if args.mock_llm:
            chat = MockChat(model_id="mock-advisory-v1")
        else:
            from supervisor.adapters.factory import make_chat_model
            from supervisor.config import load_settings

            chat = make_chat_model(load_settings())
            if chat.is_mock:
                _say("[SKIP] no LLM configured (LLM_BASE_URL empty): using the mock model")
        advice = advise(target, chat=chat)
        paths = write_outputs(advice, Path(args.out), target=target)
    except (RepoReadError, SupervisorError) as exc:
        _say(f"[FAIL] {type(exc).__name__}: {exc}")
        return 2
    except OSError as exc:
        _say(f"[FAIL] {type(exc).__name__}: {exc}")
        return 2
    except Exception as exc:  # noqa: BLE001 - the CLI prints [FAIL], never a traceback
        _say(f"[FAIL] internal error: {type(exc).__name__}")
        return 1

    r = advice.report
    f = r.found
    _say(
        f"[OK] found: {len(f.tools)} tool(s), {len(f.llm_calls)} LLM call site(s), "
        f"{len(f.data_access)} data access, {len(f.pii_fields)} personal data field(s), "
        f"{f.secrets_count} secret(s), {len(f.injection_refs)} flagged line(s)"
    )
    _say(f"[OK] readiness: {r.readiness.total} / 100")
    for a in r.readiness.areas:
        _say(f"[OK]   {a.id}: {a.points} / {a.weight}")
    _say(f"[OK] patches: {len(advice.patches)} ({len(r.needed.manual)} item(s) to do by hand)")
    _say(f"[OK] narrative source: {r.narrative.source}")
    for name in sorted(paths):
        _say(f"[OK] wrote {paths[name]}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

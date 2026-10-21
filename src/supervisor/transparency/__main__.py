"""Transparency report CLI (WP31). ASCII output.

  python -m supervisor.transparency build AGENT [--variant V] [--format F] [--lang L] --out DIR
      write a PREVIEW of the report from the current facts (not signed, nothing on the chain);
      V is regulator, customer, internal or all; F is json, html, pdf or all; L is vi, en or both
  python -m supervisor.transparency generate AGENT|--all [--force]
      build, version and sign the reports (files, rows and a chain record); run only when the
      app is stopped (one chain writer per lane) or use the app's job
  python -m supervisor.transparency list
      the latest version per agent and variant

Needs TRANSPARENCY_ENABLED=1. Files are never overwritten. The chain check of the lane is made
by ``build --verify`` and always by ``generate``.
"""

from __future__ import annotations

from supervisor.bootstrap import bootstrap

bootstrap()

import argparse  # noqa: E402
import sys  # noqa: E402
from pathlib import Path  # noqa: E402

from supervisor.core.errors import SupervisorError  # noqa: E402
from supervisor.transparency.model import (  # noqa: E402
    FORMATS,
    LANGS,
    VARIANTS,
    TransparencyError,
)


def _say(text: str) -> None:
    print(text.encode("ascii", "replace").decode("ascii"))  # noqa: T201


def _write(out: Path, name: str, data: bytes) -> Path:
    out.mkdir(parents=True, exist_ok=True)
    path = out / name
    try:
        with path.open("xb") as fh:
            fh.write(data)
    except FileExistsError:
        raise TransparencyError(f"refusing to overwrite an existing file: {path}") from None
    return path


def _build(args: argparse.Namespace) -> int:
    from supervisor.adapters.factory import build_adapters, make_masker
    from supervisor.config import load_settings
    from supervisor.jobs import bootstrap_schema
    from supervisor.transparency import render
    from supervisor.transparency.model import ensure_on
    from supervisor.transparency.service import TransparencyService

    settings = load_settings()
    ensure_on(settings)
    adapters = build_adapters(settings)
    try:
        if adapters.executor.dialect == "sqlite":
            bootstrap_schema.run(settings, adapters)
        svc = TransparencyService.from_adapters(adapters, masker=make_masker(settings))
        variants = VARIANTS if args.variant == "all" else (args.variant,)
        formats = FORMATS if args.format == "all" else (args.format,)
        langs = LANGS if args.lang == "both" else (args.lang,)
        for variant in variants:
            report = svc.preview(args.agent, variant, fresh_verify=args.verify)
            for fmt in formats:
                if fmt == "json":
                    path = _write(
                        args.out,
                        f"transparency-{args.agent}-{variant}.json",
                        render.render_json(report),
                    )
                    _say(f"[OK] {path}")
                    continue
                for lang in langs:
                    name = f"transparency-{args.agent}-{variant}.{lang}"
                    if fmt == "html":
                        path = _write(args.out, name + ".html", render.render_html(report, lang))
                    else:
                        res = render.render_pdf(report, lang, font_path=svc.pdf_font)
                        if res.fmt != "pdf":
                            _say(f"[SKIP] {name}.pdf: {res.notice}")
                            continue
                        path = _write(args.out, name + ".pdf", res.data)
                    _say(f"[OK] {path}")
    finally:
        adapters.close()
    return 0


def _generate(args: argparse.Namespace) -> int:
    from supervisor.jobs import transparency as job
    from supervisor.monitors.jobctx import standalone
    from supervisor.transparency.model import ensure_on

    with standalone() as (settings, _, ctx):
        ensure_on(settings)
        svc = job.service_for(ctx, settings)
        agents = svc.facts.running_agents() if args.all else [args.agent]
        for agent in agents:
            for r in svc.generate(agent, actor="cli:transparency", force=args.force):
                extra = (
                    f" diff_changed={len(r['diff']['changed'])}" if r["status"] == "made" else ""
                )
                _say(f"[OK] {agent} {r['variant']}: {r['status']} v{r['version']}{extra}")
    return 0


def _list(_args: argparse.Namespace) -> int:
    from supervisor.adapters.factory import build_adapters, make_masker
    from supervisor.config import load_settings
    from supervisor.jobs import bootstrap_schema
    from supervisor.transparency.model import ensure_on
    from supervisor.transparency.service import TransparencyService

    settings = load_settings()
    ensure_on(settings)
    adapters = build_adapters(settings)
    try:
        if adapters.executor.dialect == "sqlite":
            bootstrap_schema.run(settings, adapters)
        svc = TransparencyService.from_adapters(adapters, masker=make_masker(settings))
        for row in svc.overview():
            cells = [
                f"{v}=v{x['version']}" if (x := row["variants"][v]) else f"{v}=-" for v in VARIANTS
            ]
            _say(f"{row['agent_id']:<24} {row['status']:<10} " + " ".join(cells))
    finally:
        adapters.close()
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="python -m supervisor.transparency", description=__doc__)
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("build")
    p.add_argument("agent")
    p.add_argument("--variant", choices=(*VARIANTS, "all"), default="regulator")
    p.add_argument("--format", choices=(*FORMATS, "all"), default="html")
    p.add_argument("--lang", choices=(*LANGS, "both"), default="en")
    p.add_argument("--out", type=Path, required=True)
    p.add_argument("--verify", action="store_true", help="run the offline chain check now")
    p = sub.add_parser("generate")
    p.add_argument("agent", nargs="?")
    p.add_argument("--all", action="store_true")
    p.add_argument("--force", action="store_true")
    sub.add_parser("list")
    args = ap.parse_args(argv)
    if args.cmd == "generate" and not (args.agent or args.all):
        ap.error("generate needs an AGENT or --all")
    try:
        return {"build": _build, "generate": _generate, "list": _list}[args.cmd](args)
    except SupervisorError as exc:
        _say(f"[FAIL] {exc}")
        return 1


if __name__ == "__main__":
    sys.exit(main())

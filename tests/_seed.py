"""WP-T1: seed once per process, copy per test.

Building a SQLite store (DDL + migrate) takes about 0.6 s and the demo replay about 0.9 s. Over
thousands of tests that was the largest cost. Each pytest process (one per xdist worker) builds a
template data directory once; a test gets a file copy of it in its own ``tmp_path``. Nothing is
shared between tests or between workers: the template is read only, the copy is private.

Two templates: ``bare`` (schema bootstrapped) and ``replayed`` (the demo replay run behind the
real gateway, four incidents)."""

from __future__ import annotations

import atexit
import shutil
import tempfile
from pathlib import Path
from typing import Any

from supervisor.adapters.factory import Adapters, build_adapters
from supervisor.config import load_settings
from supervisor.jobs import bootstrap_schema

_TEMPLATES: dict[str, Path] = {}


def _build(kind: str) -> Path:
    root = Path(tempfile.mkdtemp(prefix=f"sup-seed-{kind}-"))
    atexit.register(shutil.rmtree, root, True)
    data = root / "data"
    settings = load_settings(sql_backend="sqlite", data_dir=data, llm_base_url="")
    a = build_adapters(settings)
    try:
        bootstrap_schema.run(a.settings, a)
        if kind == "replayed":
            from supervisor.demo import replay as R

            report = R.run_gated(a.settings, adapters=a)
            assert report.ok, "\n".join(report.lines)
    finally:
        a.close()
    return data


def template(kind: str) -> Path:
    if kind not in _TEMPLATES:
        _TEMPLATES[kind] = _build(kind)
    return _TEMPLATES[kind]


def adapters_from_template(kind: str, data_dir: Path, **settings: Any) -> Adapters:
    """A fresh store: a copy of the template in ``data_dir`` (a path inside the test's tmp_path)."""
    shutil.copytree(template(kind), data_dir)
    s = load_settings(sql_backend="sqlite", data_dir=data_dir, llm_base_url="", **settings)
    return build_adapters(s)

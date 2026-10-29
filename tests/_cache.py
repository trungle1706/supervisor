"""WP-T1: per-process caches for the two slowest repeated computations in the suite.

* ``_Loader.run`` (the RegKB load: YAML parse, JSON-schema check, source sha256 check) takes 1 to
  2 s and 24 MB of regulation files are read each time. It is deterministic in the content of the
  files it reads, so the result is cached under a key made of the sha256 of every file under the
  directories it reads (and the date it uses). A test that writes an override or an internal
  document changes that content, so it gets a fresh load. ``clear_regkb_cache()`` drops it anyway
  (tests/regkb/test_w2_change.py and tests/console/test_w2_change.py call it).
* The detector harness report used by the console "detectors" tab tests (24 s a run).

Each pytest process (each xdist worker) has its own caches; nothing is shared between workers.
Errors are never cached."""

from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path
from typing import Any

_REGKB: dict[str, Any] = {}
_HARNESS: dict[str, Any] = {}
_ORIGINAL_RUN: Any = None
_FILE_SHA: dict[tuple[str, int, int], str] = {}  # (path, size, mtime_ns) -> sha256


def _sha(path: Path) -> str:
    st = path.stat()
    key = (str(path), st.st_size, st.st_mtime_ns)
    got = _FILE_SHA.get(key)
    if got is None:
        got = hashlib.sha256(path.read_bytes()).hexdigest()
        _FILE_SHA[key] = got
    return got


def _tree_signature(root: Path | None) -> list[tuple[str, str]]:
    if root is None or not root.exists():
        return [("", "absent")]
    return [
        (p.relative_to(root).as_posix(), _sha(p)) for p in sorted(root.rglob("*")) if p.is_file()
    ]


def regkb_key(loader: Any) -> str:
    from supervisor.regkb import loader as L

    parts: list[Any] = [
        str(loader.root),
        str(loader.internal_dir),
        str(loader.docs_dir),
        str(loader.overrides_dir),
        L._today().isoformat(),
        [_tree_signature(d) for d in (loader.root, loader.internal_dir, loader.docs_dir)],
        _tree_signature(loader.overrides_dir),
        # the schema dir may be the repository's when the root has none
        _tree_signature(L.REPO_ROOT / "regulations" / "schema"),
    ]
    return hashlib.sha256(json.dumps(parts, default=str).encode()).hexdigest()


def clear_regkb_cache() -> None:
    _REGKB.clear()


def install_regkb_cache() -> None:
    global _ORIGINAL_RUN
    from supervisor.regkb import loader as L

    if _ORIGINAL_RUN is not None:
        return
    _ORIGINAL_RUN = L._Loader.run

    def run(self: Any) -> Any:
        key = regkb_key(self)
        if key not in _REGKB:
            _REGKB[key] = _ORIGINAL_RUN(self)  # raises on a bad tree: not cached
        return _REGKB[key]

    L._Loader.run = run  # type: ignore[method-assign]


def cached_detector_report(**kw: Any) -> dict[str, Any]:
    """``supervisor.detectors.harness.run(**kw)``, once per process per config file content."""
    from supervisor.config import REPO_ROOT
    from supervisor.detectors import harness

    key = json.dumps([kw, _sha(REPO_ROOT / "config" / "detectors.yaml")], sort_keys=True)
    if key not in _HARNESS:
        _HARNESS[key] = harness.run(**kw)
    return copy.deepcopy(_HARNESS[key])


__all__ = ["cached_detector_report", "clear_regkb_cache", "install_regkb_cache"]

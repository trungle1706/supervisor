"""Offline parsers for Python dependency files -> :class:`Component` rows.

Supported: ``uv.lock`` and ``poetry.lock`` (TOML via ``tomllib``), ``Pipfile.lock`` (JSON),
``requirements*.txt`` (PEP 508 lines, ``--hash=sha256:``, markers, extras, continuation
lines) and ``pyproject.toml`` (``[project].dependencies``, optional dependencies and
``[dependency-groups]``). No network, no subprocess. A file that cannot be read or parsed
is recorded in ``DepSet.errors`` and never raises.

A *lock* source (uv.lock, poetry.lock, Pipfile.lock, or a requirements file that carries
hashes) gives exact versions and hashes. ``pyproject.toml`` ranges are only *declared*:
they become components only for names that no lock source covers, and they are pinned
only when written ``==x.y.z``.
"""

from __future__ import annotations

import json
import re
import tomllib
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from pathlib import Path

LOCK_NAMES = ("uv.lock", "poetry.lock", "pipfile.lock")
_MAX_BYTES = 20 * 1024 * 1024


def normalise_name(name: str) -> str:
    """PEP 503 normalisation: lower case, runs of ``-_.`` become one ``-``."""
    return re.sub(r"[-_.]+", "-", name).lower()


@dataclass(frozen=True)
class Component:
    name: str  # PEP 503 normalised
    version: str  # "" when not pinned
    pinned: bool
    hashes: tuple[str, ...]  # sha256 hex digests (no "sha256:" prefix), sorted, unique
    source: str  # registry | git | path | url | editable | declared | unknown
    is_direct: bool
    origin: str = ""  # file name the row came from
    spec: str = ""  # the declared specifier text, when known (requirements / pyproject)

    @property
    def hashed(self) -> bool:
        return bool(self.hashes)

    def key(self) -> tuple[str, str]:
        return (self.name, self.version)


@dataclass
class DepSet:
    components: list[Component] = field(default_factory=list)
    files: list[str] = field(default_factory=list)  # file names that were parsed
    errors: list[str] = field(default_factory=list)
    lock_present: bool = False
    declared_only: bool = False  # components come from pyproject ranges only

    def sorted_components(self) -> list[Component]:
        return sorted(self.components, key=lambda c: (c.name, c.version, c.origin))


def _clean_hashes(values: Iterable[str]) -> tuple[str, ...]:
    out = set()
    for v in values:
        v = str(v).strip()
        if v.lower().startswith("sha256:"):
            v = v[7:]
        if re.fullmatch(r"[0-9a-fA-F]{64}", v):
            out.add(v.lower())
    return tuple(sorted(out))


def _read_text(path: Path) -> str | None:
    try:
        if path.stat().st_size > _MAX_BYTES:
            return None
        return path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None


# --------------------------------------------------------------------------- lock files


def _uv_source_kind(src: object) -> str:
    if not isinstance(src, dict):
        return "unknown"
    for kind in ("registry", "git", "url", "path", "directory", "editable", "virtual"):
        if kind in src:
            return {"directory": "path", "virtual": "editable"}.get(kind, kind)
    return "unknown"


def parse_uv_lock(text: str, origin: str = "uv.lock") -> list[Component]:
    data = tomllib.loads(text)
    pkgs = data.get("package", [])
    direct: set[str] = set()
    roots: set[str] = set()
    for p in pkgs:
        if _uv_source_kind(p.get("source")) == "editable":
            roots.add(normalise_name(str(p.get("name", ""))))
            groups: list[list[dict]] = [p.get("dependencies", [])]
            groups += list((p.get("optional-dependencies") or {}).values())
            groups += list((p.get("dev-dependencies") or {}).values())
            for grp in groups:
                for d in grp:
                    if isinstance(d, dict) and "name" in d:
                        direct.add(normalise_name(str(d["name"])))
    out: list[Component] = []
    for p in pkgs:
        name = normalise_name(str(p.get("name", "")))
        kind = _uv_source_kind(p.get("source"))
        if not name or name in roots and kind == "editable":
            continue  # the project itself is not a dependency
        hashes: list[str] = []
        if isinstance(p.get("sdist"), dict) and p["sdist"].get("hash"):
            hashes.append(p["sdist"]["hash"])
        for w in p.get("wheels", []) or []:
            if isinstance(w, dict) and w.get("hash"):
                hashes.append(w["hash"])
        version = str(p.get("version", ""))
        out.append(
            Component(
                name=name,
                version=version,
                pinned=bool(version),
                hashes=_clean_hashes(hashes),
                source=kind,
                is_direct=name in direct,
                origin=origin,
            )
        )
    return out


def parse_poetry_lock(text: str, origin: str = "poetry.lock") -> list[Component]:
    data = tomllib.loads(text)
    out: list[Component] = []
    for p in data.get("package", []):
        name = normalise_name(str(p.get("name", "")))
        if not name:
            continue
        src = p.get("source") or {}
        stype = str(src.get("type", "registry")) if isinstance(src, dict) else "registry"
        kind = {"legacy": "registry", "directory": "path", "file": "path"}.get(stype, stype)
        files = p.get("files") or []
        hashes = _clean_hashes(f.get("hash", "") for f in files if isinstance(f, dict))
        version = str(p.get("version", ""))
        out.append(
            Component(
                name=name,
                version=version,
                pinned=bool(version),
                hashes=hashes,
                source=kind,
                is_direct=False,
                origin=origin,
            )
        )
    return out


def parse_pipfile_lock(text: str, origin: str = "Pipfile.lock") -> list[Component]:
    data = json.loads(text)
    out: list[Component] = []
    for section in ("default", "develop"):
        for raw_name, info in (data.get(section) or {}).items():
            if not isinstance(info, dict):
                continue
            ver = str(info.get("version", ""))
            exact = ver[2:] if ver.startswith("==") and "*" not in ver else ""
            kind = "git" if "git" in info else "path" if "path" in info else "registry"
            out.append(
                Component(
                    name=normalise_name(raw_name),
                    version=exact,
                    pinned=bool(exact),
                    hashes=_clean_hashes(info.get("hashes", []) or []),
                    source=kind,
                    is_direct=False,
                    origin=origin,
                    spec=ver,
                )
            )
    return out


# --------------------------------------------------------------------------- PEP 508


_REQ = re.compile(r"^([A-Za-z0-9](?:[A-Za-z0-9._-]*[A-Za-z0-9])?)\s*(\[[^\]]*\])?\s*(.*)$")
_HASH = re.compile(r"--hash[= ]\s*sha256:([0-9a-fA-F]{64})")


def parse_requirement(line: str, origin: str = "") -> Component | None:
    """One PEP 508 requirement (with optional ``--hash`` options). ``None`` if not one."""
    hashes = _clean_hashes(m for m in _HASH.findall(line))
    body = _HASH.sub("", line)
    body = re.sub(r"\s--?[A-Za-z][\w-]*(?:[= ]\S+)?\s*$", "", body).strip()
    body = body.split(" #", 1)[0].strip()
    m = _REQ.match(body)
    if not m:
        return None
    name, rest = m.group(1), m.group(3).strip()
    marker_split = rest.split(";", 1)
    spec_part = marker_split[0].strip()
    source = "registry"
    version = ""
    if spec_part.startswith("@"):
        url = spec_part[1:].strip()
        source = "git" if url.startswith("git+") else "url"
    else:
        for piece in spec_part.strip("()").split(","):
            piece = piece.strip()
            mm = re.fullmatch(r"===?\s*([A-Za-z0-9_.!+-]+)", piece)
            if mm and "*" not in piece:
                version = mm.group(1)
    return Component(
        name=normalise_name(name),
        version=version,
        pinned=bool(version),
        hashes=hashes,
        source=source,
        is_direct=True,
        origin=origin,
        spec=spec_part,
    )


def _logical_lines(text: str) -> list[str]:
    out: list[str] = []
    buf = ""
    for raw in text.splitlines():
        line = raw.rstrip()
        if line.endswith("\\"):
            buf += line[:-1] + " "
            continue
        buf += line
        out.append(buf)
        buf = ""
    if buf:
        out.append(buf)
    return out


def parse_requirements(text: str, origin: str = "requirements.txt") -> list[Component]:
    out: list[Component] = []
    for raw in _logical_lines(text):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("-e ") or line.startswith("--editable"):
            continue  # editable local paths are not registry dependencies
        if line.startswith("-"):
            continue  # -r, -c, --index-url, ... (includes are not followed: offline, bounded)
        comp = parse_requirement(line, origin)
        if comp is not None:
            out.append(comp)
    return out


def _pyproject_requirements(data: dict) -> list[str]:
    reqs: list[str] = list((data.get("project") or {}).get("dependencies", []) or [])
    for grp in ((data.get("project") or {}).get("optional-dependencies") or {}).values():
        reqs += [r for r in grp if isinstance(r, str)]
    for grp in (data.get("dependency-groups") or {}).values():
        reqs += [r for r in grp if isinstance(r, str)]
    return reqs


def parse_pyproject(text: str, origin: str = "pyproject.toml") -> list[Component]:
    data = tomllib.loads(text)
    out: list[Component] = []
    for r in _pyproject_requirements(data):
        comp = parse_requirement(r, origin)
        if comp is not None:
            out.append(
                Component(
                    name=comp.name,
                    version=comp.version,
                    pinned=comp.pinned,
                    hashes=(),
                    source="declared",
                    is_direct=True,
                    origin=origin,
                    spec=comp.spec,
                )
            )
    return out


# --------------------------------------------------------------------------- entry point


def _kind_of(path: Path) -> str:
    n = path.name.lower()
    if n == "uv.lock":
        return "uv"
    if n == "poetry.lock":
        return "poetry"
    if n == "pipfile.lock":
        return "pipfile"
    if n == "pyproject.toml":
        return "pyproject"
    if n.endswith(".txt") and "requirements" in n:
        return "requirements"
    if n.endswith(".in") and "requirements" in n:
        return "requirements"
    return ""


def load_depset(paths: Sequence[Path | str]) -> DepSet:
    """Parse every recognised file in ``paths`` and merge into one :class:`DepSet`."""
    ds = DepSet()
    lock_rows: list[Component] = []
    declared: list[Component] = []
    for raw in paths:
        path = Path(raw)
        kind = _kind_of(path)
        if not kind:
            ds.errors.append(f"{path.name}: unsupported file type")
            continue
        text = _read_text(path)
        if text is None:
            ds.errors.append(f"{path.name}: cannot read file")
            continue
        try:
            if kind == "uv":
                rows, is_lock = parse_uv_lock(text, path.name), True
            elif kind == "poetry":
                rows, is_lock = parse_poetry_lock(text, path.name), True
            elif kind == "pipfile":
                rows, is_lock = parse_pipfile_lock(text, path.name), True
            elif kind == "requirements":
                rows = parse_requirements(text, path.name)
                is_lock = any(r.hashes for r in rows)
            else:
                declared += parse_pyproject(text, path.name)
                ds.files.append(path.name)
                continue
        except (tomllib.TOMLDecodeError, json.JSONDecodeError, ValueError, TypeError) as exc:
            ds.errors.append(f"{path.name}: parse error ({type(exc).__name__})")
            continue
        ds.files.append(path.name)
        lock_rows += rows
        if is_lock:
            ds.lock_present = True
    covered = {c.name for c in lock_rows}
    direct_names = {c.name for c in declared}
    merged: list[Component] = []
    seen: set[tuple[str, str, str]] = set()
    for c in lock_rows:
        if c.name in direct_names and not c.is_direct:
            c = Component(**{**c.__dict__, "is_direct": True})
        k = (c.name, c.version, c.origin)
        if k not in seen:
            seen.add(k)
            merged.append(c)
    extra = [c for c in declared if c.name not in covered]
    if extra and not lock_rows:
        ds.declared_only = True
    for c in extra:
        k = (c.name, c.version, c.origin)
        if k not in seen:
            seen.add(k)
            merged.append(c)
    ds.components = merged
    return ds

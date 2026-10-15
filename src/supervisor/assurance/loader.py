"""Load and validate the pack manifests in ``packs/*.yaml``.

Every problem of every file is collected and raised together as one :class:`PackError`
(file name first), so an author fixes all manifests in one pass. Rules on top of the
:class:`~supervisor.assurance.model.EvalPack` schema: the file is at most 64 KiB, it is
parsed with ``yaml.safe_load``, the file stem equals the pack id, and ids are unique.
"""

from __future__ import annotations

import hashlib
from collections.abc import Sequence
from pathlib import Path

import yaml
from pydantic import ValidationError

from supervisor.assurance.model import EvalPack
from supervisor.core.errors import SupervisorError

PACKS_DIR = Path(__file__).parent / "packs"
MAX_MANIFEST_BYTES = 64 * 1024


class PackError(SupervisorError):
    """One or more pack manifests are invalid. ``problems`` lists them all."""

    def __init__(self, problems: Sequence[str]) -> None:
        self.problems = list(problems)
        super().__init__("invalid eval pack manifest(s): " + "; ".join(self.problems))


def manifest_sha256(path: Path | str) -> str:
    """SHA-256 of the manifest file bytes (goes into the evidence record)."""
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def pack_path(pack_id: str, directory: Path | str = PACKS_DIR) -> Path:
    return Path(directory) / f"{pack_id}.yaml"


def _load_one(path: Path) -> tuple[EvalPack | None, list[str]]:
    name = path.name
    try:
        size = path.stat().st_size
    except OSError as exc:
        return None, [f"{name}: cannot read file ({type(exc).__name__})"]
    if size > MAX_MANIFEST_BYTES:
        return None, [f"{name}: file is {size} bytes, the limit is {MAX_MANIFEST_BYTES}"]
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (yaml.YAMLError, UnicodeDecodeError) as exc:
        return None, [f"{name}: not valid YAML ({type(exc).__name__})"]
    if not isinstance(data, dict):
        return None, [f"{name}: top level must be a mapping"]
    try:
        pack = EvalPack.model_validate(data)
    except ValidationError as exc:
        out = []
        for err in exc.errors(include_input=False, include_url=False):
            loc = ".".join(str(x) for x in err["loc"]) or "manifest"
            out.append(f"{name}: {loc}: {err['msg']}")
        return None, out
    if path.stem != pack.id:
        return None, [f"{name}: file name must equal the pack id {pack.id!r}"]
    return pack, []


def load_packs(directory: Path | str = PACKS_DIR) -> list[EvalPack]:
    """All valid packs in ``directory``, sorted by id. Raises :class:`PackError`."""
    root = Path(directory)
    problems: list[str] = []
    packs: dict[str, EvalPack] = {}
    if not root.is_dir():
        raise PackError([f"{root}: pack folder not found"])
    for path in sorted(root.glob("*.yaml")):
        pack, errs = _load_one(path)
        problems += errs
        if pack is None:
            continue
        if pack.id in packs:
            problems.append(f"{path.name}: duplicate pack id {pack.id!r}")
            continue
        packs[pack.id] = pack
    if problems:
        raise PackError(problems)
    return [packs[k] for k in sorted(packs)]

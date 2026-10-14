"""``RepoReader`` over a local directory (a git checkout or any folder). Read-only.

* Paths are relative POSIX paths under ``root``. ``..`` and absolute paths are refused;
  symlinks that leave the root are skipped.
* Size caps: ``max_file_bytes`` per file and ``max_files`` per listing.
* Binary files (NUL byte in the first 8 KiB, or a known binary suffix) are skipped:
  ``list_files`` leaves out known binary suffixes, ``read_text`` raises
  ``BinaryFileSkipped``.
* No write method exists. ``revision()`` reads the commit id through ``sandbox.git``
  (read-only subcommand) when the folder is inside a git work tree.

Repo text is untrusted data: callers scrub it (``supervisor.onboard.scrub``) before any
LLM sees it.
"""

from __future__ import annotations

import fnmatch
import os
from collections.abc import Sequence
from pathlib import Path, PurePosixPath

from supervisor.core.errors import SupervisorError

SKIP_DIRS = frozenset(
    {".git", ".venv", "venv", "__pycache__", "node_modules", ".mypy_cache", ".ruff_cache"}
)
SKIP_DIRS |= frozenset({".pytest_cache", "dist", "build", ".tox", ".idea", ".vscode"})
BINARY_SUFFIXES = frozenset(
    {
        ".png",
        ".jpg",
        ".jpeg",
        ".gif",
        ".pdf",
        ".zip",
        ".gz",
        ".tar",
        ".whl",
        ".pyc",
        ".so",
        ".dll",
        ".exe",
        ".mp4",
        ".db",
        ".sqlite",
        ".sqlite3",
        ".parquet",
        ".ttf",
        ".woff",
        ".woff2",
        ".ico",
    }
)


class RepoReadError(SupervisorError):
    """A path cannot be read (outside the root, missing, too large)."""


class BinaryFileSkipped(RepoReadError):
    """The file is binary; the Onboarding Agent does not read it."""


class FileTooLarge(RepoReadError):
    """The file is larger than the cap."""


class LocalGitRepoReader:
    """Read-only access to a folder. Implements ``core.ports.RepoReader``."""

    def __init__(
        self,
        root: str | Path,
        *,
        max_file_bytes: int = 1_000_000,
        max_files: int = 5000,
    ) -> None:
        self.root = Path(os.path.abspath(root))
        if not self.root.is_dir():
            raise RepoReadError(f"repository folder does not exist: {self.root}")
        self.max_file_bytes = max_file_bytes
        self.max_files = max_files
        self.skipped: dict[str, str] = {}  # path -> reason (binary, too_large, outside)

    # -- RepoReader -------------------------------------------------------------
    def list_files(self, pattern: str = "**/*") -> Sequence[str]:
        out: list[str] = []
        for dirpath, dirnames, filenames in os.walk(self.root, followlinks=False):
            dirnames[:] = sorted(d for d in dirnames if d not in SKIP_DIRS)
            for name in sorted(filenames):
                full = Path(dirpath) / name
                rel = full.relative_to(self.root).as_posix()
                if full.suffix.lower() in BINARY_SUFFIXES:
                    self.skipped[rel] = "binary"
                    continue
                if full.is_symlink() and not self._inside(full):
                    self.skipped[rel] = "outside"
                    continue
                if not _match(rel, pattern):
                    continue
                out.append(rel)
                if len(out) >= self.max_files:
                    return out
        return out

    def read_text(self, path: str, max_bytes: int = 1_000_000) -> str:
        full = self._resolve(path)
        cap = min(max_bytes, self.max_file_bytes)
        size = full.stat().st_size
        if size > cap:
            self.skipped[path] = "too_large"
            raise FileTooLarge(f"{path}: {size} bytes is above the cap of {cap} bytes")
        data = full.read_bytes()
        if b"\x00" in data[:8192] or full.suffix.lower() in BINARY_SUFFIXES:
            self.skipped[path] = "binary"
            raise BinaryFileSkipped(f"{path}: binary file skipped")
        return data.decode("utf-8", errors="replace")

    # -- extras -------------------------------------------------------------------
    def revision(self) -> str | None:
        """Commit id of HEAD when the root is inside a git work tree, else None."""
        from supervisor import sandbox

        try:
            res = sandbox.git(["rev-parse", "HEAD"], cwd=self.root, timeout_s=30)
        except SupervisorError:
            return None
        return res.stdout.strip() if res.ok else None

    def _inside(self, full: Path) -> bool:
        try:
            full.resolve().relative_to(self.root.resolve())
        except ValueError:
            return False
        return True

    def _resolve(self, path: str) -> Path:
        p = PurePosixPath(path.replace("\\", "/"))
        if p.is_absolute() or ".." in p.parts or not p.parts:
            raise RepoReadError(f"path must be relative and inside the repository: {path}")
        full = self.root.joinpath(*p.parts)
        if not self._inside(full):
            raise RepoReadError(f"path leaves the repository: {path}")
        if not full.is_file():
            raise RepoReadError(f"not a file: {path}")
        return full


def _match(rel: str, pattern: str) -> bool:
    if pattern in ("**/*", "*", "**"):
        return True
    if pattern.startswith("**/"):
        tail = pattern[3:]
        return fnmatch.fnmatch(rel, pattern) or fnmatch.fnmatch(rel.rsplit("/", 1)[-1], tail)
    return fnmatch.fnmatch(rel, pattern)

"""Strict unified-diff applier (stdlib only) that checks a patch without writing anything.

Why this exists: ``supervisor.sandbox.git`` does not allow ``git apply``, and widening that
allow-list is a security change. The check also has to run on the bank laptop, where git may
be missing. So the advisor checks every patch it generates against the target with this
module before it writes the patch to disk.

The rules are the strict ones: a context line or a removed line must match the file exactly
at the position the hunk header states (no fuzz, no offset search); a new file must not
exist yet; every path must stay inside the root. Supported: new files and edits of existing
files, with ``\\ No newline at end of file`` markers. Deletes, renames and mode changes
raise ``PatchError``. Line ends are kept as they are (CRLF files work).
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath

from supervisor.core.errors import SupervisorError

NO_NEWLINE = "\\ No newline at end of file"
_HUNK = re.compile(r"^@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@")
_IGNORED_HEADERS = (
    "diff --git ",
    "index ",
    "new file mode ",
    "old mode ",
    "new mode ",
    "similarity index ",
)


class PatchError(SupervisorError):
    """A patch does not apply exactly."""


def split_lines(text: str) -> list[str]:
    """Split on ``\\n`` only (keeping it); a last line without ``\\n`` is kept as it is."""
    parts = text.split("\n")
    lines = [p + "\n" for p in parts[:-1]]
    if parts[-1]:
        lines.append(parts[-1])
    return lines


@dataclass
class _Hunk:
    old_start: int
    old_len: int
    new_len: int
    body: list[tuple[str, str]] = field(default_factory=list)  # (tag, text with its "\n")


@dataclass
class _FilePatch:
    path: str
    is_new: bool
    hunks: list[_Hunk] = field(default_factory=list)


def _clean_path(raw: str) -> str:
    raw = raw.split("\t", 1)[0].strip()
    if len(raw) > 1 and raw[0] == raw[-1] == '"':
        raise PatchError(f"quoted path not supported: {raw}")
    if raw.startswith(("a/", "b/")):
        raw = raw[2:]
    return raw


def _safe_rel(root: Path, rel: str) -> Path:
    p = PurePosixPath(rel)
    if not rel or p.is_absolute() or ".." in p.parts or "\\" in rel or ":" in rel.split("/")[0]:
        raise PatchError(f"path escapes the root: {rel!r}")
    full = (root / rel).resolve()
    try:
        full.relative_to(root.resolve())
    except ValueError as exc:
        raise PatchError(f"path escapes the root: {rel!r}") from exc
    return full


def parse(diff: str) -> list[_FilePatch]:
    lines = diff.split("\n")
    if lines and lines[-1] == "":
        lines.pop()
    out: list[_FilePatch] = []
    i = 0
    while i < len(lines):
        line = lines[i]
        if line.startswith(_IGNORED_HEADERS):
            i += 1
            continue
        if line.startswith(("deleted file mode", "rename ", "copy ")):
            raise PatchError(f"unsupported patch operation: {line.split(' ', 1)[0]}")
        if line.startswith("--- "):
            old = line[4:]
            if i + 1 >= len(lines) or not lines[i + 1].startswith("+++ "):
                raise PatchError("'---' line without '+++' line")
            new = lines[i + 1][4:]
            is_new = old.split("\t", 1)[0].strip() == "/dev/null"
            if new.split("\t", 1)[0].strip() == "/dev/null":
                raise PatchError("deleting a file is not supported")
            path = _clean_path(new)
            if not is_new and _clean_path(old) != path:
                raise PatchError("renames are not supported")
            fp = _FilePatch(path=path, is_new=is_new)
            out.append(fp)
            i += 2
            while i < len(lines) and not lines[i].startswith(("--- ", "diff --git ")):
                m = _HUNK.match(lines[i])
                if not m:
                    raise PatchError(f"unexpected line in patch: {lines[i][:60]!r}")
                hunk = _Hunk(
                    old_start=int(m.group(1)),
                    old_len=int(m.group(2)) if m.group(2) is not None else 1,
                    new_len=int(m.group(4)) if m.group(4) is not None else 1,
                )
                i += 1
                old_n = new_n = 0
                while i < len(lines):
                    row = lines[i]
                    if row.startswith(NO_NEWLINE):
                        if not hunk.body:
                            raise PatchError("no-newline marker before any line")
                        tag, text = hunk.body[-1]
                        hunk.body[-1] = (tag, text[:-1] if text.endswith("\n") else text)
                        i += 1
                        continue
                    if old_n >= hunk.old_len and new_n >= hunk.new_len:
                        break  # the header counts are met: the next row is not in this hunk
                    if row[:1] in (" ", "+", "-"):
                        tag, text = row[0], row[1:] + "\n"
                    elif row == "":  # an empty context line whose space was stripped
                        tag, text = " ", "\n"
                    else:
                        break
                    hunk.body.append((tag, text))
                    old_n += tag in " -"
                    new_n += tag in " +"
                    i += 1
                if (old_n, new_n) != (hunk.old_len, hunk.new_len):
                    raise PatchError("hunk line counts do not match its header")
                fp.hunks.append(hunk)
            continue
        if line.strip() == "":
            i += 1
            continue
        raise PatchError(f"unexpected line in patch header: {line[:60]!r}")
    if not out:
        raise PatchError("no file in patch")
    return out


def _apply_one(fp: _FilePatch, old_text: str | None) -> str:
    if fp.is_new:
        if old_text is not None:
            raise PatchError(f"{fp.path}: new file already exists")
        src: list[str] = []
    else:
        if old_text is None:
            raise PatchError(f"{fp.path}: file to patch does not exist")
        src = split_lines(old_text)
    out: list[str] = []
    pos = 0  # next unconsumed source line (0-based)
    for h in fp.hunks:
        start = h.old_start if h.old_len == 0 else h.old_start - 1
        if fp.is_new and (h.old_len != 0 or start != 0):
            raise PatchError(f"{fp.path}: a new file patch must only add lines")
        if start < pos:
            raise PatchError(f"{fp.path}: hunks overlap or are out of order")
        out.extend(src[pos:start])
        pos = start
        for tag, text in h.body:
            if tag == "+":
                out.append(text)
                continue
            if pos >= len(src) or src[pos] != text:
                got = src[pos].rstrip("\n")[:60] if pos < len(src) else "<end of file>"
                raise PatchError(
                    f"{fp.path}:{pos + 1}: patch expects {text.rstrip(chr(10))[:60]!r}, "
                    f"file has {got!r}"
                )
            if tag == " ":
                out.append(text)
            pos += 1
    out.extend(src[pos:])
    # A line without a final newline may only be the last line of the file.
    for k, line in enumerate(out[:-1]):
        if not line.endswith("\n"):
            raise PatchError(f"{fp.path}: line {k + 1} lacks a newline in the middle of the file")
    return "".join(out)


def apply_patch(root: Path, diff: str) -> dict[str, str]:
    """New text of every file the diff touches (key: repo-relative path). Nothing is written."""
    root = Path(root)
    result: dict[str, str] = {}
    for fp in parse(diff):
        full = _safe_rel(root, fp.path)
        old: str | None = None
        if full.exists():
            if not full.is_file():
                raise PatchError(f"{fp.path}: not a regular file")
            try:
                old = full.read_bytes().decode("utf-8")
            except UnicodeDecodeError as exc:
                raise PatchError(f"{fp.path}: not UTF-8 text") from exc
        if fp.path in result:
            old = result[fp.path]
        result[fp.path] = _apply_one(fp, old)
    return result


def check_patch(root: Path, diff: str) -> None:
    """Raise ``PatchError`` unless the diff applies exactly to ``root``."""
    apply_patch(root, diff)

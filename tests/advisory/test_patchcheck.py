"""(h) the strict diff applier, and the diff writer that feeds it."""

from __future__ import annotations

from pathlib import Path

import pytest

from supervisor.advisory.integration.patchcheck import PatchError, apply_patch, check_patch
from supervisor.advisory.integration.patches import (
    GateSpec,
    apply_tool_gates,
    make_diff,
)

OLD = "a\nb\nc\nd\ne\nf\ng\nh\n"


def test_round_trip_edit(tmp_path: Path) -> None:
    (tmp_path / "x.txt").write_text(OLD, encoding="utf-8", newline="")
    new = "a\nb\nC\nd\ne\nf\ng\nh\ni\n"
    out = apply_patch(tmp_path, make_diff("x.txt", OLD, new))
    assert out == {"x.txt": new}
    assert (tmp_path / "x.txt").read_text(encoding="utf-8") == OLD  # nothing written


def test_new_file(tmp_path: Path) -> None:
    diff = make_diff("d/n.txt", None, "one\ntwo\n")
    assert "--- /dev/null" in diff
    assert apply_patch(tmp_path, diff) == {"d/n.txt": "one\ntwo\n"}
    (tmp_path / "d").mkdir()
    (tmp_path / "d" / "n.txt").write_text("x", encoding="utf-8")
    with pytest.raises(PatchError, match="already exists"):
        check_patch(tmp_path, diff)


def test_context_mismatch_raises(tmp_path: Path) -> None:
    (tmp_path / "x.txt").write_text(OLD, encoding="utf-8", newline="")
    diff = make_diff("x.txt", OLD, OLD.replace("c\n", "C\n"))
    (tmp_path / "x.txt").write_text(OLD.replace("b\n", "B\n"), encoding="utf-8", newline="")
    with pytest.raises(PatchError):
        check_patch(tmp_path, diff)


def test_no_offset_search(tmp_path: Path) -> None:
    diff = make_diff("x.txt", OLD, OLD.replace("c\n", "C\n"))
    (tmp_path / "x.txt").write_text("zz\n" + OLD, encoding="utf-8", newline="")
    with pytest.raises(PatchError):
        check_patch(tmp_path, diff)  # same lines, one line lower: strict position fails


def test_removed_line_must_match(tmp_path: Path) -> None:
    (tmp_path / "x.txt").write_text("a\nXX\nc\n", encoding="utf-8", newline="")
    diff = "--- a/x.txt\n+++ b/x.txt\n@@ -1,3 +1,2 @@\n a\n-b\n c\n"
    with pytest.raises(PatchError):
        check_patch(tmp_path, diff)


def test_missing_file_raises(tmp_path: Path) -> None:
    with pytest.raises(PatchError, match="does not exist"):
        check_patch(tmp_path, make_diff("x.txt", OLD, OLD + "i\n"))


@pytest.mark.parametrize("bad", ["../evil.txt", "/etc/evil.txt", "a/../../evil.txt"])
def test_path_escape_raises(tmp_path: Path, bad: str) -> None:
    diff = f"--- /dev/null\n+++ b/{bad}\n@@ -0,0 +1 @@\n+x\n"
    with pytest.raises(PatchError, match="escapes"):
        check_patch(tmp_path, diff)


def test_symlink_escape_raises(tmp_path: Path) -> None:
    outside = tmp_path / "outside"
    outside.mkdir()
    root = tmp_path / "root"
    root.mkdir()
    (root / "link").symlink_to(outside, target_is_directory=True)
    diff = "--- /dev/null\n+++ b/link/n.txt\n@@ -0,0 +1 @@\n+x\n"
    with pytest.raises(PatchError, match="escapes"):
        check_patch(root, diff)


@pytest.mark.parametrize(
    ("old", "new"),
    [
        ("a\nb", "a\nb\nc"),  # no newline before and after
        ("a\nb\n", "a\nb"),  # newline removed
        ("a\nb", "a\nb\n"),  # newline added
        ("a\nb", "a\nB"),  # last line changed, still no newline
        ("a\r\nb\r\n", "a\r\nb\r\nc\r\n"),  # CRLF kept
    ],
)
def test_no_newline_at_eof_round_trip(tmp_path: Path, old: str, new: str) -> None:
    (tmp_path / "f.txt").write_bytes(old.encode())
    diff = make_diff("f.txt", old, new)
    assert apply_patch(tmp_path, diff) == {"f.txt": new}


def test_marker_is_written() -> None:
    assert "\\ No newline at end of file" in make_diff("f.txt", "a\nb", "a\nc")


def test_count_mismatch_raises(tmp_path: Path) -> None:
    (tmp_path / "x.txt").write_text("a\nb\n", encoding="utf-8")
    with pytest.raises(PatchError):
        check_patch(tmp_path, "--- a/x.txt\n+++ b/x.txt\n@@ -1,2 +1,3 @@\n a\n b\n")


def test_delete_is_not_supported(tmp_path: Path) -> None:
    (tmp_path / "x.txt").write_text("a\n", encoding="utf-8")
    with pytest.raises(PatchError):
        check_patch(tmp_path, "--- a/x.txt\n+++ /dev/null\n@@ -1 +0,0 @@\n-a\n")


def test_two_hunks_and_ascending(tmp_path: Path) -> None:
    old = "".join(f"l{i}\n" for i in range(40))
    new = old.replace("l2\n", "L2\n").replace("l35\n", "L35\n")
    (tmp_path / "x.txt").write_text(old, encoding="utf-8", newline="")
    diff = make_diff("x.txt", old, new)
    assert diff.count("@@ -") == 2
    assert apply_patch(tmp_path, diff) == {"x.txt": new}


# --- the tool-gate codemod -----------------------------------------------------------

SRC = '''"""Tools."""
import os

from langchain_core.tools import tool


@tool
def pay(amount: int, to: str) -> str:
    return "ok"


async def other(x):
    return x
'''
SPEC = [GateSpec("pay", "@supervised_tool(...)")]


def test_codemod_is_idempotent_and_places_decorator_below_framework_one() -> None:
    new, names = apply_tool_gates(SRC, SPEC, hook_import="import supervisor_onboard")
    assert names == ["pay"]
    lines = new.splitlines()
    i = lines.index("@supervised_tool(...)")
    assert lines[i - 1] == "@tool" and lines[i + 1].startswith("def pay")
    assert lines.index("from langchain_core.tools import tool") < lines.index(
        "from supervisor.gateway.sdk import supervised_tool  # supervisor-onboard: hook"
    )
    again, names2 = apply_tool_gates(new, SPEC, hook_import="import supervisor_onboard")
    assert again == new and names2 == []


def test_codemod_without_imports_goes_after_the_docstring() -> None:
    src = '"""Doc."""\n\n\ndef pay(a):\n    return a\n'
    new, _ = apply_tool_gates(src, SPEC[:0] + [GateSpec("pay", "@d")], hook_import="import h")
    assert new.splitlines()[0] == '"""Doc."""'
    assert new.splitlines()[1].startswith("from supervisor.gateway.sdk")


def test_codemod_keeps_crlf() -> None:
    src = SRC.replace("\n", "\r\n")
    new, _ = apply_tool_gates(src, SPEC, hook_import="import supervisor_onboard")
    assert "\r\n" in new and "\n" not in new.replace("\r\n", "")

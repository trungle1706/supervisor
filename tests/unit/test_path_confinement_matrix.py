"""Clean-up audit D13: one shared matrix over the path and name confinement checks.

The 11 checks have different contracts on purpose (a bare file name, a relative path, a URL path,
a folder that must stay outside another). They are not merged. This test feeds the same hostile
inputs to every check and freezes what each one does today, so that a later merge, or a change
to one check, shows up as a changed row. Every check must refuse ``..``, an absolute path and a
drive path in the cases its contract covers (the ``MUST_REFUSE`` table); a row that differs from
``EXPECTED`` fails with the check name and the input.
"""

from __future__ import annotations

import sys
from collections.abc import Callable
from pathlib import Path
from types import SimpleNamespace

import pytest

INPUTS: tuple[str, ...] = (
    "ok.txt",
    "sub/ok.txt",
    "../x",
    "..\\x",
    "a/../b",
    "..",
    "/etc/passwd",
    "C:/x",
    "C:\\x",
    "\\\\host\\share\\x",
    "a\x00b",
    "%2e%2e/x",
    "%2e%2e%2fx",
    ".hidden",
    " ok.txt",
)

HEX64 = "a" * 64


def _root(tmp: Path) -> Path:
    root = tmp / "root"
    (root / "sub").mkdir(parents=True)
    (root / "ok.txt").write_text("x", encoding="utf-8")
    (root / "sub" / "ok.txt").write_text("x", encoding="utf-8")
    (tmp / "x").write_text("secret", encoding="utf-8")
    return root


def _accepts(fn: Callable[[], object], *errors: type[BaseException]) -> bool:
    try:
        fn()
    except errors:
        return False
    return True


# Each adapter returns True when the check lets the input through. The error types are the
# ones the check raises for a refusal; any other exception is a test failure.


def _backup(tmp: Path, name: str) -> bool:
    from supervisor.ops.backup import BackupError, safe_db_path

    return _accepts(lambda: safe_db_path(_root(tmp), name), BackupError)


def _patchcheck(tmp: Path, name: str) -> bool:
    from supervisor.advisory.integration.patchcheck import PatchError, _safe_rel

    return _accepts(lambda: _safe_rel(_root(tmp), name), PatchError)


def _local_git(tmp: Path, name: str) -> bool:
    from supervisor.adapters.repo.local_git import LocalGitRepoReader, RepoReadError

    return _accepts(lambda: LocalGitRepoReader(_root(tmp))._resolve(name), RepoReadError)


def _instrument_inside(tmp: Path, name: str) -> bool:
    """Opposite contract: the folder must stay OUTSIDE the target. True = allowed outside."""
    from supervisor.onboard.instrument import InstrumentError, check_dirs

    root = _root(tmp)
    return _accepts(lambda: check_dirs(root, root / name), InstrumentError)


def _anchor(tmp: Path, name: str) -> bool:
    from supervisor.evidence.anchor import AnchorError, _check_name

    return _accepts(lambda: _check_name(name), AnchorError)


def _regkb_package(tmp: Path, name: str) -> bool:
    from supervisor.regkb.package import PackageError, check_member_path

    return _accepts(lambda: check_member_path(name), PackageError)


def _regkb_change(tmp: Path, name: str) -> bool:
    from supervisor.regkb.change import ChangeError, find_incoming

    data = tmp / "data"
    pkg = data / "regkb" / "incoming" / HEX64
    (pkg / "incoming" / "VN-INST1" / "2026-01-01").mkdir(parents=True, exist_ok=True)
    (pkg / "import.json").write_text("{}", encoding="utf-8")
    (pkg / "incoming" / "VN-INST1" / "2026-01-01" / "ok.txt").write_text("t", encoding="utf-8")
    (pkg / "incoming" / "secret.txt").write_text("t", encoding="utf-8")
    full = "VN-INST1/2026-01-01/ok.txt" if name == "ok.txt" else f"VN-INST1/{name}"
    return _accepts(lambda: find_incoming(data, HEX64, "VN-INST1", full), ChangeError)


def _reports_folder(tmp: Path, name: str) -> bool:
    from supervisor.console.integration_reports import IntegrationInputError, _folder

    settings = SimpleNamespace(integration_reports_dir=str(tmp / "reports"), data_dir=str(tmp))
    (tmp / "reports" / "ok.txt").mkdir(parents=True, exist_ok=True)
    return _accepts(lambda: _folder(settings, name), IntegrationInputError)


def _reports_patch(tmp: Path, name: str) -> bool:
    from supervisor.console.integration_reports import IntegrationInputError, patch_path

    settings = SimpleNamespace(integration_reports_dir=str(tmp / "reports"), data_dir=str(tmp))
    folder = tmp / "reports" / "r1"
    (folder / "patches").mkdir(parents=True, exist_ok=True)
    (folder / "ok.patch").write_text("p", encoding="utf-8")
    file = "ok.patch" if name == "ok.txt" else name
    return _accepts(lambda: patch_path(settings, "r1", file), IntegrationInputError)


def _http_target_path(tmp: Path, name: str) -> bool:
    from supervisor.assurance.targets import TargetError, http_target_config

    path = "/" + name if name == "ok.txt" else name
    block = {"url": "https://agent.example.com", "path": path}
    return _accepts(
        lambda: http_target_config(block, allowed_hosts=["agent.example.com"]), TargetError
    )


def _intake(tmp: Path, name: str) -> bool:
    from supervisor.onboard.intake import _bad_path

    return not _bad_path(name)


def _questionnaire(tmp: Path, name: str) -> bool:
    from supervisor.advisory.compliance.questionnaire import CONTROL_FIELDS, _check_value

    f = next(x for x in CONTROL_FIELDS if x.name == "policy_files")
    problems: list[str] = []
    _check_value(f, [name], "controls.policy_files", (), problems)
    return not problems


CHECKS: dict[str, Callable[[Path, str], bool]] = {
    "ops.backup.safe_db_path": _backup,
    "advisory.patchcheck._safe_rel": _patchcheck,
    "adapters.local_git._resolve": _local_git,
    "onboard.instrument.check_dirs": _instrument_inside,
    "evidence.anchor._check_name": _anchor,
    "regkb.package.check_member_path": _regkb_package,
    "regkb.change.find_incoming": _regkb_change,
    "console.integration_reports._folder": _reports_folder,
    "console.integration_reports.patch_path": _reports_patch,
    "assurance.targets.http_target_config.path": _http_target_path,
    "onboard.intake._bad_path": _intake,
    "advisory.questionnaire.policy_files": _questionnaire,
}

# One letter per input in the order of ``INPUTS``: T = the check lets it through, F = it refuses.
# Columns:  ok.txt  sub/ok.txt  ../x  ..\\x  a/../b  ..  /etc/passwd  C:/x  C:\\x  UNC  NUL
#           %2e%2e/x  %2e%2e%2fx  .hidden  " ok.txt"
EXPECTED: dict[str, str] = {
    "ops.backup.safe_db_path": "TFFFFFFFFFFFTTF",
    "advisory.patchcheck._safe_rel": "TTFFFFFFFFFTTTT",
    "adapters.local_git._resolve": "TTFFFFFFFFFFFFF",
    "onboard.instrument.check_dirs": "FFTFFTTFFFTFFFF",
    "evidence.anchor._check_name": "TFFFFFFFFFTFTFT",
    "regkb.package.check_member_path": "TTFFFFFFFFFTTTT",
    "regkb.change.find_incoming": "TFFFFFFFFFFFFFF",
    "console.integration_reports._folder": "TFFFFFFFFFFFFFF",
    "console.integration_reports.patch_path": "TFFFFFFFFFFFFFF",
    "assurance.targets.http_target_config.path": "TFFFFFTFFFFFFFF",
    "onboard.intake._bad_path": "TTFFFFFFFFFTTTT",
    "advisory.questionnaire.policy_files": "TTFTFFFTTTTTTTT",
}

# Contract notes for the rows above:
# * onboard.instrument.check_dirs has the opposite contract: a folder must stay OUTSIDE the
#   target, so True means "allowed outside" and ok.txt (inside) is refused.
# * assurance.targets checks a URL path: a leading / is correct there, and C: is only
#   a character the path pattern refuses.
# * No check decodes percent escapes. %2e%2e/x is a literal name. A caller that decodes the
#   text after the check would bypass every row that lets it through.
# * advisory.questionnaire.policy_files uses pathlib.Path: on Linux a backslash is a name
#   character, so ..\x and the drive paths pass there (on Windows they are refused). The
#   frozen table is therefore Linux only; the policy files are read relative to a repo the
#   operator already trusts (hand-written questionnaire answers).

ALWAYS_REFUSE = ("../x", "a/../b", "..")
ABSOLUTE = "/etc/passwd"
# Checks for which the input above is not a refusal case (different contract, see notes).
NOT_APPLICABLE = {
    "onboard.instrument.check_dirs": ("../x", "..", ABSOLUTE),
    "assurance.targets.http_target_config.path": (ABSOLUTE,),
}


@pytest.mark.skipif(sys.platform == "win32", reason="the questionnaire row is Path based")
@pytest.mark.parametrize("check", sorted(CHECKS))
def test_matrix_is_frozen(check: str, tmp_path: Path) -> None:
    got = tuple(CHECKS[check](tmp_path / str(i), name) for i, name in enumerate(INPUTS))
    want = tuple(c == "T" for c in EXPECTED[check])
    diff = [(n, w, g) for n, w, g in zip(INPUTS, want, got, strict=True) if w != g]
    assert not diff, f"{check} changed (input, expected, got): {diff}"


@pytest.mark.parametrize("check", sorted(CHECKS))
@pytest.mark.parametrize("name", (*ALWAYS_REFUSE, ABSOLUTE))
def test_dotdot_and_absolute_are_refused(check: str, name: str, tmp_path: Path) -> None:
    if name in NOT_APPLICABLE.get(check, ()):
        pytest.skip("different contract; see the notes")
    assert CHECKS[check](tmp_path, name) is False, f"{check} lets {name!r} through"


def test_every_check_accepts_the_plain_name_it_is_built_for(tmp_path: Path) -> None:
    refused = [
        c
        for c, fn in sorted(CHECKS.items())
        if c != "onboard.instrument.check_dirs" and not fn(tmp_path / c, "ok.txt")
    ]
    assert refused == []  # a check that refuses everything would pass the tests above


def test_patchcheck_nul_byte_is_a_patch_error(tmp_path: Path) -> None:
    """A NUL byte in a patch path is refused as ``PatchError`` (HTTP 400), not ``ValueError``."""
    from supervisor.advisory.integration.patchcheck import PatchError, _safe_rel

    root = _root(tmp_path)
    with pytest.raises(PatchError):
        _safe_rel(root, "a\x00b")
    with pytest.raises(PatchError):
        _safe_rel(root, "sub/ok.txt\x00")

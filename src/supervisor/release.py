"""Hand-off release zip (WP11, bank guide sections 6 and 7).

    python -m supervisor.cli release --out <dir> [--nexus] [--wheelhouse]

Steps (every external command goes through ``supervisor.sandbox``):

1. ``git archive HEAD`` of the repository into a zip (committed files only: nothing
   from the working tree, no ``.git``, nothing git-ignored);
2. ``requirements.txt`` regenerated from ``uv.lock`` (same command as
   ``supervisor.cli export-reqs``); the release fails if the committed file is stale;
3. ``uv.toml`` with the bank Nexus index (``--nexus``). It exists only inside the zip,
   never in the repository (git-ignored; a test checks);
4. ``HANDOFF.md``: the cmd checklist for the bank laptop;
5. optional ``wheelhouse/`` (``--wheelhouse``): Windows cp311 wheels via
   ``pip download``; reported as [SKIP] with the reason when this host cannot do it;
6. leak sweep over every entry of the final zip: ``.env``, ``*.db``, ``.venv``,
   ``__pycache__``, model files, ``data/local``, run data, key files, the secret regexes
   of ``tests/test_no_secrets.py``, and real ``dbc-`` hosts outside
   ``docs/BANK_DEPLOY_GUIDE.md``. Any hit fails the release, deletes the zip and prints
   the offending paths.

Output: ``<out>/supervisor-<version>-<sha>.zip`` with one top folder ``supervisor/``.
"""

from __future__ import annotations

import argparse
import fnmatch
import re
import shutil
import tempfile
import zipfile
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from pathlib import Path

from supervisor import __version__, sandbox
from supervisor.config import REPO_ROOT
from supervisor.core.errors import SandboxError, SupervisorError

TOP = "supervisor"
NEXUS_UV_TOML = """\
# Bank Nexus index (docs/BANK_DEPLOY_GUIDE.md section 2.1). Only in the hand-off zip;
# never committed. Run uv from the folder that contains this file.
[[index]]
url = "https://nexus-dev.techcombank.com.vn/repository/pypi-common-proxy/simple/"
default = true

allow-insecure-host = ["nexus-dev.techcombank.com.vn"]
"""

EXPORT_REQS_ARGV = [
    "uv",
    "export",
    "--frozen",
    "--no-dev",
    "--extra",
    "databricks",
    "--no-hashes",
    "--no-emit-project",
    "--no-header",
]

# ---------------------------------------------------------------- leak sweep rules

PATH_RULES: tuple[tuple[str, str], ...] = (
    (".env file", "*/.env"),
    (".env file", "*/.env.*"),
    ("database file", "*.db"),
    ("database file", "*.sqlite"),
    ("database file", "*.sqlite3"),
    ("database file", "*.db-wal"),
    ("database file", "*.db-shm"),
    ("virtual env", "*/.venv/*"),
    ("python cache", "*/__pycache__/*"),
    ("python cache", "*.pyc"),
    ("key file", "*.pem"),
    ("key file", "*.key"),
    ("key file", "*.p12"),
    ("key file", "*.pfx"),
    ("model file", "*.gguf"),
    ("model file", "*.safetensors"),
    ("model file", "*.onnx"),
    ("model file", "*.pt"),
    ("model file", "*.pth"),
    ("model file", "*.ckpt"),
    ("model file", "*.bin"),
    ("local data", "*/data/local/*"),
    ("run data", "*/runs/*"),
    ("run data", "*/spool/*"),
    ("run data", "*/.supervisor-demo"),
    ("run data", "*/.demo-snapshot/*"),
    ("run data", "*/casefiles/*"),
    ("run data", "*/anchors/*"),
    ("git metadata", "*/.git/*"),
)
ALLOWED_PATHS = {f"{TOP}/.env.example"}

# Same patterns as tests/test_no_secrets.py (kept in sync by a test).
SECRET_PATTERNS: dict[str, re.Pattern[str]] = {
    "databricks workspace host": re.compile(r"\bdbc-[0-9a-f]{8}-[0-9a-f]{4}\b"),
    "azure databricks host": re.compile(r"\badb-\d{8,}\.\d+\.azuredatabricks\.net"),
    "databricks PAT": re.compile(r"\bdapi[0-9a-f]{32}\b"),
    "warehouse http path": re.compile(r"/sql/1\.0/warehouses/[0-9a-f]{16}\b"),
    "private key": re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----"),
    "openai-style key": re.compile(r"\bsk-[A-Za-z0-9_-]{20,}"),
    "github token": re.compile(r"\bgh[pousr]_[A-Za-z0-9]{30,}"),
    "aws access key": re.compile(r"\bAKIA[0-9A-Z]{16}\b"),
    "assigned DATABRICKS_TOKEN": re.compile(r"DATABRICKS_TOKEN\s*=\s*['\"]?[A-Za-z0-9]{8,}"),
}
# The reference guide names the bank workspace on purpose (owner hand-over document).
SECRET_ALLOW = {("databricks workspace host", f"{TOP}/docs/BANK_DEPLOY_GUIDE.md")}
BINARY_SUFFIXES = (".whl", ".zip", ".png", ".jpg", ".jpeg", ".gif", ".pdf", ".mp4", ".ico")
WHEEL_RE = re.compile(r"\.whl$")


class ReleaseError(SupervisorError):
    """The release cannot be built."""


@dataclass
class ReleaseReport:
    lines: list[str] = field(default_factory=list)
    ok: bool = True
    zip_path: Path | None = None
    entries: list[str] = field(default_factory=list)
    leaks: list[str] = field(default_factory=list)

    def say(self, line: str) -> None:
        self.lines.append(line)

    def fail(self, text: str) -> None:
        self.ok = False
        self.lines.append(f"[FAIL] {text}")


def handoff_md(*, nexus: bool, version: str, sha: str, wheelhouse: bool) -> str:
    """The cmd checklist for the bank laptop (Windows cmd syntax)."""
    install = (
        "uv sync --python 3.11 --extra databricks --offline --find-links wheelhouse"
        if wheelhouse
        else "uv sync --python 3.11 --extra databricks"
    )
    nexus_note = (
        "`uv.toml` in this folder points uv at the bank Nexus index. Run every `uv` command "
        "from this folder. If uv reports `UnknownIssuer`, add `--native-tls`."
        if nexus
        else "No `uv.toml` in this zip (built without `--nexus`): uv uses its default index."
    )
    return f"""# Supervisor hand-off {version} ({sha})

Built with `python -m supervisor.cli release` from `git archive HEAD`, leak-swept.
{nexus_note}

## Checklist (Windows cmd)

1. Copy the zip to the laptop and unzip it, for example to `C:\\work\\`. Then:

   ```
   cd C:\\work\\supervisor
   ```

2. Install (Python 3.11):

   ```
   {install}
   ```

3. Check the environment (prints [OK] / [FAIL] / [SKIP] with the fix):

   ```
   uv run python -m supervisor.cli preflight
   ```

4. Start the app:

   ```
   uv run python -m supervisor.cli serve
   ```

5. Open http://127.0.0.1:8000/console/ in the browser.

6. Run the demo (second cmd window, same folder; no network needed):

   ```
   uv run python -m supervisor.cli demo
   ```

   Stage mode (console and demo keys in one process): stop `serve` first, then
   `uv run python -m supervisor.cli demo seed` and `uv run python -m supervisor.cli demo serve`.
   See `docs\\DEMO.md`.

## Cheat sheet

| Need | Command |
|---|---|
| Tests | `uv run python -m pytest -q` |
| Demo 20 times | `uv run python -m supervisor.cli demo --loop 20 --quiet` |
| Reset the demo | `uv run python -m supervisor.cli demo reset` |
| Verify an evidence export | `uv run python -m supervisor.cli verify <export dir> --strict` |
| Runbook, symptom -> fix | `docs\\RUNBOOK.md` |

Never use `uv run pytest` or `uv run uvicorn` (AppLocker blocks the .exe stubs).
Never set `DATABRICKS_TOKEN` (OAuth only).
"""


def sweep_paths(names: Sequence[str]) -> list[str]:
    hits = []
    for name in names:
        if name in ALLOWED_PATHS or name.endswith("/"):
            continue
        probe = "/" + name  # fnmatch "*" also matches "/"
        for label, pattern in PATH_RULES:
            if fnmatch.fnmatch(probe, pattern):
                hits.append(f"{name}: {label}")
                break
    return hits


def sweep_text(name: str, text: str) -> list[str]:
    hits = []
    for label, pat in SECRET_PATTERNS.items():
        if (label, name) in SECRET_ALLOW:
            continue
        for m in pat.finditer(text):
            if "FILL-ME" in m.group(0):
                continue
            line = text.count("\n", 0, m.start()) + 1
            hits.append(f"{name}:{line}: {label}")
    return hits


def leak_sweep(zip_path: Path) -> list[str]:
    """Offending paths (and lines) in the zip. Empty list = clean."""
    with zipfile.ZipFile(zip_path) as zf:
        names = zf.namelist()
        hits = sweep_paths(names)
        for name in names:
            if name.endswith("/") or name.lower().endswith(BINARY_SUFFIXES):
                continue
            text = zf.read(name).decode("utf-8", errors="ignore")
            hits.extend(sweep_text(name, text))
    return hits


def _git(repo: Path, *args: str, timeout_s: float = 120.0) -> sandbox.RunResult:
    return sandbox.run(["git", *args], cwd=repo, timeout_s=timeout_s)


def _ascii(text: str) -> str:
    return text.encode("ascii", "backslashreplace").decode("ascii")


def try_wheelhouse(requirements: Path, dest: Path) -> tuple[bool, str]:
    """Download Windows cp311 wheels. Returns (ok, message). Never raises."""
    argv = [
        sandbox.python_executable(),
        "-m",
        "pip",
        "download",
        "--only-binary=:all:",
        "--platform",
        "win_amd64",
        "--python-version",
        "3.11",
        "--implementation",
        "cp",
        "--abi",
        "cp311",
        "-r",
        str(requirements),
        "-d",
        str(dest),
    ]
    try:
        res = sandbox.run(argv, cwd=dest.parent, timeout_s=900)
    except SandboxError as exc:
        return False, str(exc)
    if not res.ok:
        tail = (res.stderr or res.stdout).strip().splitlines()
        return False, (tail[-1] if tail else f"pip exited {res.returncode}")[:200]
    wheels = [p for p in dest.iterdir() if WHEEL_RE.search(p.name)]
    if not wheels:
        return False, "pip download produced no wheels"
    return True, f"{len(wheels)} wheels"


def build_release(
    out_dir: Path,
    *,
    repo: Path = REPO_ROOT,
    nexus: bool = False,
    wheelhouse: bool = False,
    echo: Callable[[str], None] | None = None,
    wheel_fetcher: Callable[[Path, Path], tuple[bool, str]] = try_wheelhouse,
) -> ReleaseReport:
    rep = ReleaseReport()

    def say(line: str) -> None:
        rep.say(line)
        if echo:
            echo(_ascii(line))

    def fail(text: str) -> ReleaseReport:
        rep.fail(text)
        if echo:
            echo(_ascii(rep.lines[-1]))
        return rep

    repo = Path(repo).resolve()
    out_dir = Path(out_dir).resolve()
    if out_dir == repo or repo in out_dir.parents:
        if (repo / ".gitignore").is_file() and not _git(
            repo, "check-ignore", "-q", str(out_dir)
        ).ok:
            return fail(f"--out {out_dir} is inside the repository and not git-ignored")
    head = _git(repo, "rev-parse", "--short=12", "HEAD")
    if not head.ok:
        return fail(f"not a git repository with a commit: {repo} ({head.stderr.strip()[:120]})")
    sha = head.stdout.strip()
    say(f"[OK] repository {repo} at HEAD {sha}")
    dirty = _git(repo, "status", "--porcelain", "--untracked-files=no")
    if dirty.ok and dirty.stdout.strip():
        say("[SKIP] working tree has uncommitted changes: they are NOT in the zip (HEAD only)")
    out_dir.mkdir(parents=True, exist_ok=True)
    final = out_dir / f"supervisor-{__version__}-{sha}.zip"

    with tempfile.TemporaryDirectory(prefix="supervisor-release-") as tmp_s:
        tmp = Path(tmp_s)
        archive = tmp / "head.zip"
        res = _git(repo, "archive", "--format=zip", f"--prefix={TOP}/", "-o", str(archive), "HEAD")
        if not res.ok:
            return fail(f"git archive failed: {res.stderr.strip()[:200]}")
        say(f"[OK] git archive HEAD -> {archive.name}")

        reqs = tmp / "requirements.txt"
        try:
            exp = sandbox.run([*EXPORT_REQS_ARGV, "-o", str(reqs)], cwd=repo, timeout_s=300)
        except SandboxError as exc:
            return fail(f"uv export: {exc}. Install uv, or run on the build host")
        if not exp.ok:
            return fail(f"uv export failed: {exp.stderr.strip()[:200]}")
        with zipfile.ZipFile(archive) as zf:
            name = f"{TOP}/requirements.txt"
            committed = zf.read(name) if name in zf.namelist() else b""
        if committed.replace(b"\r\n", b"\n") != reqs.read_bytes().replace(b"\r\n", b"\n"):
            return fail(
                "requirements.txt in HEAD differs from uv.lock. Fix: "
                "python -m supervisor.cli export-reqs, commit, release again"
            )
        say("[OK] requirements.txt regenerated from uv.lock (matches HEAD)")

        wheel_dir: Path | None = None
        if wheelhouse:
            wheel_dir = tmp / "wheelhouse"
            wheel_dir.mkdir()
            ok, msg = wheel_fetcher(reqs, wheel_dir)
            if ok:
                say(f"[OK] wheelhouse: {msg} (win_amd64, cp311)")
            else:
                say(f"[SKIP] wheelhouse: cannot download Windows cp311 wheels here: {msg}")
                wheel_dir = None

        tmp_zip = tmp / final.name
        with (
            zipfile.ZipFile(archive) as src,
            zipfile.ZipFile(tmp_zip, "w", zipfile.ZIP_DEFLATED) as dst,
        ):
            for info in src.infolist():
                if info.filename == f"{TOP}/requirements.txt":
                    continue
                dst.writestr(info, src.read(info.filename))
            dst.write(reqs, f"{TOP}/requirements.txt")
            if nexus:
                dst.writestr(f"{TOP}/uv.toml", NEXUS_UV_TOML)
                say("[OK] uv.toml (bank Nexus index) added to the zip only")
            else:
                say("[SKIP] uv.toml: not added (use --nexus for the bank laptop)")
            dst.writestr(
                f"{TOP}/HANDOFF.md",
                handoff_md(
                    nexus=nexus, version=__version__, sha=sha, wheelhouse=wheel_dir is not None
                ),
            )
            if wheel_dir is not None:
                for whl in sorted(wheel_dir.iterdir()):
                    dst.write(whl, f"{TOP}/wheelhouse/{whl.name}")
        say("[OK] HANDOFF.md (cmd checklist) added")

        leaks = leak_sweep(tmp_zip)
        with zipfile.ZipFile(tmp_zip) as zf:
            rep.entries = zf.namelist()
        if leaks:
            rep.leaks = leaks
            rep.fail(f"leak sweep: {len(leaks)} hit(s); release NOT written:")
            if echo:
                echo(rep.lines[-1])
            for hit in leaks:
                line = f"       {hit}"
                rep.lines.append(line)
                if echo:
                    echo(_ascii(line))
            return rep
        say(f"[OK] leak sweep: {len(rep.entries)} entries, 0 hits")
        if final.exists():
            final.unlink()
        shutil.move(str(tmp_zip), str(final))
    rep.zip_path = final
    size_kb = final.stat().st_size // 1024
    say(f"[OK] release written: {final} ({size_kb} KB)")
    return rep


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="python -m supervisor.cli release",
        description="Build the hand-off zip from git HEAD (leak-swept).",
    )
    p.add_argument("--out", default=None, help="output folder (default: dist)")
    p.add_argument("--nexus", action="store_true", help="add uv.toml with the bank Nexus index")
    p.add_argument(
        "--wheelhouse",
        action="store_true",
        help="also try to download Windows cp311 wheels into wheelhouse/",
    )
    p.add_argument("--repo", default=None, help=argparse.SUPPRESS)
    return p


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(list(argv) if argv is not None else None)
    out = Path(args.out) if args.out else REPO_ROOT / "dist"
    try:
        rep = build_release(
            out,
            repo=Path(args.repo) if args.repo else REPO_ROOT,
            nexus=args.nexus,
            wheelhouse=args.wheelhouse,
            echo=lambda line: print(line, flush=True),  # noqa: T201 (CLI output)
        )
    except (SupervisorError, OSError, zipfile.BadZipFile) as exc:
        print(_ascii(f"[FAIL] release: {type(exc).__name__}: {exc}"))  # noqa: T201
        return 1
    return 0 if rep.ok else 1


__all__ = [
    "NEXUS_UV_TOML",
    "SECRET_PATTERNS",
    "ReleaseError",
    "ReleaseReport",
    "build_release",
    "handoff_md",
    "leak_sweep",
    "main",
    "sweep_paths",
    "sweep_text",
]

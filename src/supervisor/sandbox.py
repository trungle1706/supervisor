"""The only module allowed to start child processes (AST test enforces this).

Rules: argv lists only (never ``shell=True``), absolute executable and cwd,
explicit timeout, output captured as text.
"""

from __future__ import annotations

import os
import queue
import shutil
import subprocess
import sys
import threading
from dataclasses import dataclass
from pathlib import Path

from supervisor.core.errors import SandboxError


@dataclass(frozen=True)
class RunResult:
    argv: tuple[str, ...]
    returncode: int
    stdout: str
    stderr: str

    @property
    def ok(self) -> bool:
        return self.returncode == 0


def python_executable() -> str:
    """Absolute path of the running interpreter.

    ``abspath`` (not ``realpath``): realpath follows the venv symlink to the base
    interpreter and loses the venv packages.
    """
    return os.path.abspath(sys.executable)


def which(name: str) -> str | None:
    found = shutil.which(name)
    return os.path.abspath(found) if found else None


def run(
    argv: list[str],
    *,
    cwd: str | Path,
    timeout_s: float = 120.0,
    env: dict[str, str] | None = None,
) -> RunResult:
    """Run ``argv`` and capture its output. Never raises for a non-zero exit."""
    if not argv:
        raise SandboxError("empty argv")
    exe = argv[0]
    if not os.path.isabs(exe):
        resolved = which(exe)
        if resolved is None:
            raise SandboxError(f"executable not found on PATH: {exe}")
        exe = resolved
    cwd_abs = os.path.abspath(cwd)
    if not os.path.isdir(cwd_abs):
        raise SandboxError(f"working directory does not exist: {cwd_abs}")
    full_env = dict(os.environ)
    if env:
        full_env.update(env)
    try:
        proc = subprocess.run(  # noqa: S603 - argv list, no shell
            [exe, *argv[1:]],
            cwd=cwd_abs,
            env=full_env,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout_s,
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        raise SandboxError(f"timed out after {timeout_s:.0f} s: {argv[0]}") from exc
    except OSError as exc:
        raise SandboxError(f"cannot start {argv[0]}: {exc}") from exc
    return RunResult(tuple([exe, *argv[1:]]), proc.returncode, proc.stdout, proc.stderr)


class Process:
    """A long-running child process (for example a server in a test). Stop it."""

    def __init__(self, popen: subprocess.Popen[str]) -> None:
        self._p = popen

    @property
    def pid(self) -> int:
        return self._p.pid

    def running(self) -> bool:
        return self._p.poll() is None

    def stop(self, timeout_s: float = 10.0) -> int:
        if self._p.poll() is None:
            self._p.terminate()
            try:
                self._p.wait(timeout=timeout_s)
            except subprocess.TimeoutExpired:
                self._p.kill()
                self._p.wait(timeout=timeout_s)
        return self._p.returncode


def start(argv: list[str], *, cwd: str | Path, env: dict[str, str] | None = None) -> Process:
    """Start ``argv`` in the background. Output is discarded. Caller must stop()."""
    if not argv:
        raise SandboxError("empty argv")
    exe = argv[0] if os.path.isabs(argv[0]) else which(argv[0])
    if exe is None:
        raise SandboxError(f"executable not found on PATH: {argv[0]}")
    full_env = dict(os.environ)
    if env:
        full_env.update(env)
    try:
        popen = subprocess.Popen(  # noqa: S603 - argv list, no shell
            [exe, *argv[1:]],
            cwd=os.path.abspath(cwd),
            env=full_env,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            text=True,
        )
    except OSError as exc:
        raise SandboxError(f"cannot start {argv[0]}: {exc}") from exc
    return Process(popen)


class PipeProcess:
    """A child process with stdin/stdout pipes (line based). Stop it when done."""

    def __init__(self, popen: subprocess.Popen[str]) -> None:
        self._p = popen
        self._lines: queue.Queue[str | None] = queue.Queue()
        self._reader = threading.Thread(target=self._pump, daemon=True)
        self._reader.start()

    def _pump(self) -> None:
        out = self._p.stdout
        try:
            if out is not None:
                for line in out:
                    self._lines.put(line.rstrip("\r\n"))
        except (OSError, ValueError):
            pass
        finally:
            self._lines.put(None)

    def running(self) -> bool:
        return self._p.poll() is None

    def send_line(self, line: str) -> None:
        """Write one line (newline added) to the child stdin. Raises SandboxError."""
        if self._p.stdin is None:
            raise SandboxError("child stdin is closed")
        try:
            self._p.stdin.write(line.rstrip("\r\n") + "\n")
            self._p.stdin.flush()
        except (OSError, ValueError) as exc:
            raise SandboxError(f"cannot write to child: {exc}") from exc

    def read_line(self, timeout_s: float) -> str | None:
        """Next stdout line without newline, or None on timeout or end of output."""
        try:
            item = self._lines.get(timeout=timeout_s)
        except queue.Empty:
            return None
        if item is None:
            self._lines.put(None)  # keep the end marker for later reads
        return item

    def stop(self, timeout_s: float = 10.0) -> int:
        if self._p.stdin is not None:
            try:
                self._p.stdin.close()
            except (OSError, ValueError):
                pass
        if self._p.poll() is None:
            self._p.terminate()
            try:
                self._p.wait(timeout=timeout_s)
            except subprocess.TimeoutExpired:
                self._p.kill()
                self._p.wait(timeout=timeout_s)
        self._reader.join(timeout=2.0)
        return self._p.returncode


def start_pipes(
    argv: list[str], *, cwd: str | Path, env: dict[str, str] | None = None
) -> PipeProcess:
    """Start ``argv`` with stdin/stdout pipes (utf-8 text, line buffered). stderr is discarded."""
    if not argv:
        raise SandboxError("empty argv")
    exe = argv[0] if os.path.isabs(argv[0]) else which(argv[0])
    if exe is None:
        raise SandboxError(f"executable not found on PATH: {argv[0]}")
    full_env = dict(os.environ)
    if env:
        full_env.update(env)
    try:
        popen = subprocess.Popen(  # noqa: S603 - argv list, no shell
            [exe, *argv[1:]],
            cwd=os.path.abspath(cwd),
            env=full_env,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
            encoding="utf-8",
            errors="replace",
            bufsize=1,
        )
    except OSError as exc:
        raise SandboxError(f"cannot start {argv[0]}: {exc}") from exc
    return PipeProcess(popen)


# --------------------------------------------------------------------------- git (WP9)

# Subcommands the Onboarding Agent may run. Never merge, push, pull, fetch or rebase:
# the agent prepares a branch in a local clone and a human opens and merges the PR.
# Per subcommand: the exact flags allowed. Any other argument that starts with "-" is
# refused (git accepts abbreviations and attached short forms, so a deny-list is not
# enough). Flags in GIT_VALUE_FLAGS take the next argument as a plain value.
GIT_FLAGS: dict[str, frozenset[str]] = {
    "add": frozenset({"--all", "--"}),
    "branch": frozenset({"--list", "--show-current"}),
    "checkout": frozenset({"--quiet", "-q", "-b"}),
    "clone": frozenset({"--quiet", "-q", "--no-hardlinks"}),
    "commit": frozenset({"--quiet", "-q", "--no-verify", "-m"}),
    "diff": frozenset({"--stat", "--name-only", "--"}),
    "init": frozenset({"--quiet", "-q", "-b"}),
    "log": frozenset({"--oneline", "--format=%H", "--format=%s", "-n", "--"}),
    "ls-files": frozenset({"--cached", "--others", "--exclude-standard", "--"}),
    "rev-parse": frozenset({"--show-toplevel", "--show-prefix", "--abbrev-ref", "--verify"}),
    "show": frozenset({"--name-only", "--format=", "--stat"}),
    "status": frozenset({"--porcelain", "--short", "--"}),
    "switch": frozenset({"--quiet", "-q", "-c"}),
}
GIT_ALLOWED = frozenset(GIT_FLAGS)
GIT_VALUE_FLAGS = frozenset({"-m", "-b", "-n"})


def git(
    args: list[str],
    *,
    cwd: str | Path,
    timeout_s: float = 60.0,
    identity: tuple[str, str] | None = None,
) -> RunResult:
    """Run one allowed ``git`` subcommand with hooks, prompts and signing off.

    ``identity`` (name, email) sets the author and committer for this call only.

    Raises ``SandboxError`` for a forbidden subcommand (merge, push, pull, fetch,
    rebase, remote, ...) or a forbidden option."""
    if not args:
        raise SandboxError("empty git command")
    sub = args[0]
    if sub not in GIT_ALLOWED:
        raise SandboxError(
            f"git {sub} is not allowed (the Onboarding Agent never merges or pushes)"
        )
    allowed = GIT_FLAGS[sub]
    rest = args[1:]
    i = 0
    after_dashdash = False
    while i < len(rest):
        a = rest[i]
        if not after_dashdash and a.startswith("-"):
            if a not in allowed:
                raise SandboxError(f"git option {a} is not allowed for git {sub}")
            if a == "--":
                after_dashdash = True
            elif a in GIT_VALUE_FLAGS:
                i += 1  # the value (commit message, branch name, count) is data
        elif "::" in a:
            raise SandboxError(f"git argument {a!r} is not allowed (transport syntax)")
        i += 1
    exe = which("git")
    if exe is None:
        raise SandboxError("git is not installed or not on PATH")
    argv = [
        exe,
        "-c",
        "core.hooksPath=" + os.devnull,
        "-c",
        "commit.gpgsign=false",
        "-c",
        "credential.helper=",
        "-c",
        "protocol.ext.allow=never",
        "-c",
        "protocol.allow=user",
    ]
    if identity is not None:
        argv += ["-c", f"user.name={identity[0]}", "-c", f"user.email={identity[1]}"]
    argv += args
    env = {
        "GIT_TERMINAL_PROMPT": "0",
        "GIT_ASKPASS": "",
        "GIT_CONFIG_NOSYSTEM": "1",
        "GIT_ALLOW_PROTOCOL": "file",
    }
    return run(argv, cwd=cwd, timeout_s=timeout_s, env=env)


def git_clone_https(url: str, dest: str | Path, *, timeout_s: float = 120.0) -> RunResult:
    """WP-O1: shallow clone of one ``https://`` URL into ``dest`` (a new folder).

    The caller (``onboard.intake``) has already checked the host against ONBOARD_GIT_HOSTS and
    refused credentials in the URL. Only the https transport is allowed here (the general
    ``git`` helper above allows file paths only); hooks, prompts, credential helpers, symlink
    checkout and redirects are off. Depth 1, one branch, no tags."""
    if not url.startswith("https://") or "::" in url:
        raise SandboxError("git clone: only an https:// URL is allowed")
    exe = which("git")
    if exe is None:
        raise SandboxError("git is not installed or not on PATH")
    dest_abs = Path(os.path.abspath(dest))
    dest_abs.parent.mkdir(parents=True, exist_ok=True)
    argv = [
        exe,
        "-c",
        "core.hooksPath=" + os.devnull,
        "-c",
        "credential.helper=",
        "-c",
        "protocol.allow=never",
        "-c",
        "protocol.https.allow=always",
        "-c",
        "core.symlinks=false",
        "-c",
        "http.followRedirects=false",
        "clone",
        "--quiet",
        "--depth",
        "1",
        "--single-branch",
        "--no-tags",
        "--",
        url,
        str(dest_abs),
    ]
    env = {
        "GIT_TERMINAL_PROMPT": "0",
        "GIT_ASKPASS": "",
        "GIT_CONFIG_NOSYSTEM": "1",
        "GIT_ALLOW_PROTOCOL": "https",
    }
    return run(argv, cwd=dest_abs.parent, timeout_s=timeout_s, env=env)

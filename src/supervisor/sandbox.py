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

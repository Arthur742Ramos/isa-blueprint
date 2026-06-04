"""Cross-platform subprocess helper for invoking the Isabelle wrapper.

This module exists to work around two Windows-specific failure modes that make
naive ``subprocess.run(capture_output=True, timeout=...)`` calls hang against a
locally installed Isabelle:

1. **Inherited stdin.** The Windows ``isabelle`` shim is a multi-layer wrapper
   (``isabelle.CMD`` -> ``powershell -File isabelle.ps1`` -> a Cygwin
   ``bash -lc`` login shell -> the real ``isabelle`` script). A login shell that
   inherits the parent's stdin blocks indefinitely waiting for input. We always
   redirect stdin from ``DEVNULL`` to avoid this.

2. **Post-timeout pipe draining.** ``subprocess.run(..., timeout=T)`` kills only
   the immediate child on timeout, then calls ``communicate()`` to drain the
   stdout/stderr *pipes*. Surviving grandchildren (poly/ML, bash, powershell)
   inherit the pipe write-ends, so EOF never arrives and ``communicate()`` hangs
   forever -- meaning ``TimeoutExpired`` is never actually raised. To avoid this
   we redirect stdout/stderr to **temp files** instead of pipes and use
   ``Popen.wait(timeout=...)``. With files there is nothing to drain, so
   ``wait()`` raises ``TimeoutExpired`` promptly and we then best-effort kill the
   whole process tree.

The implementation is dependency-free (stdlib only): the project declares only
PyYAML and Jinja2, so we deliberately avoid ``psutil``. Tree termination uses
``taskkill /F /T /PID`` on Windows and ``os.killpg`` on POSIX.
"""

from __future__ import annotations

import os
import subprocess
import tempfile
from dataclasses import dataclass
from typing import Any


@dataclass
class RunResult:
    """Minimal stand-in for :class:`subprocess.CompletedProcess`."""

    args: list[str]
    returncode: int
    stdout: str
    stderr: str


def _kill_tree(proc: subprocess.Popen, pgid: int | None) -> None:
    """Best-effort termination of ``proc`` and all of its descendants.

    On Windows this relies on ``taskkill /T`` walking the parent/child process
    tree. On POSIX it signals the process group captured at spawn time. Neither
    is a hard sandbox -- a descendant that fully detaches/re-parents may survive
    -- but both reliably reap the Isabelle wrapper chain we spawn here.
    """

    if proc.poll() is not None:
        return
    if os.name == "nt":
        try:
            subprocess.run(
                ["taskkill", "/F", "/T", "/PID", str(proc.pid)],
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                check=False,
                timeout=30,
            )
        except Exception:
            proc.kill()
    else:
        import signal

        try:
            if pgid is not None:
                os.killpg(pgid, signal.SIGKILL)  # type: ignore[attr-defined]
            else:
                proc.kill()
        except (ProcessLookupError, PermissionError):
            proc.kill()
    try:
        proc.wait(timeout=10)
    except subprocess.TimeoutExpired:
        pass


def run_capture(
    cmd,
    *,
    cwd=None,
    timeout: float | None = None,
    encoding: str = "utf-8",
) -> RunResult:
    """Run ``cmd``, capturing stdout/stderr to temp files.

    Always redirects stdin from ``DEVNULL``. If ``timeout`` is exceeded the whole
    process tree is killed and :class:`subprocess.TimeoutExpired` is raised with
    whatever output was captured so far. Decoding uses ``errors="replace"`` so
    stray non-UTF-8 bytes (e.g. cp1252 on a Windows console) never crash us.
    """

    args = [str(part) for part in cmd]

    popen_kwargs: dict[str, Any] = {}
    pgid: int | None = None
    if os.name == "nt":
        # Lets us optionally send Ctrl events later; taskkill /T does the actual
        # tree walk regardless of this flag.
        popen_kwargs["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP  # type: ignore[attr-defined]
    else:
        popen_kwargs["start_new_session"] = True

    with tempfile.TemporaryFile() as out, tempfile.TemporaryFile() as err:
        proc = subprocess.Popen(
            args,
            cwd=str(cwd) if cwd is not None else None,
            stdin=subprocess.DEVNULL,
            stdout=out,
            stderr=err,
            **popen_kwargs,
        )
        if os.name != "nt":
            try:
                pgid = os.getpgid(proc.pid)  # type: ignore[attr-defined]
            except OSError:
                pgid = None
        try:
            proc.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            _kill_tree(proc, pgid)
            out.seek(0)
            err.seek(0)
            raise subprocess.TimeoutExpired(
                args,
                timeout if timeout is not None else 0.0,
                output=out.read().decode(encoding, "replace"),
                stderr=err.read().decode(encoding, "replace"),
            ) from None
        out.seek(0)
        err.seek(0)
        return RunResult(
            args=args,
            returncode=proc.returncode,
            stdout=out.read().decode(encoding, "replace"),
            stderr=err.read().decode(encoding, "replace"),
        )

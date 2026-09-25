"""A best-effort single-writer lock so two builds never interleave writes into one verdict cache.

The lock is a file holding the owner's PID. Acquisition refuses only when the recorded PID is
*still alive*; a stale lock (owner gone — killed, crashed, machine rebooted mid-build) is silently
taken over. That asymmetry is exactly what durability needs: after a hard kill the next run must be
free to resume from the verdict cache, not be locked out forever by the dead owner's file.

Liveness is probed **without ever signalling the process** — on Windows ``os.kill(pid, 0)`` does not
mean "does this exist?" but "TerminateProcess with exit code 0", which would *kill* a running build.
So the check opens a query-only handle instead, and can never harm the process it is asking about.
"""

from __future__ import annotations

import os


def _alive(pid: int) -> bool:
    """True if ``pid`` is a live process, probed without disturbing it (see module docstring)."""
    if pid <= 0:
        return False
    if os.name == "nt":
        import ctypes
        from ctypes import wintypes

        PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
        STILL_ACTIVE = 259
        kernel32 = ctypes.windll.kernel32
        handle = kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
        if not handle:
            return False  # no such process (a genuinely dead PID cannot be opened at all)
        try:
            code = wintypes.DWORD()
            if not kernel32.GetExitCodeProcess(handle, ctypes.byref(code)):
                return True  # opened but unreadable: assume alive rather than risk stomping it
            return code.value == STILL_ACTIVE
        finally:
            kernel32.CloseHandle(handle)
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True  # exists but owned by someone else — alive for our purposes
    return True


class RunLock:
    """A PID lockfile: refuses only against a *live* owner, silently takes over a stale one."""

    def __init__(self, path: str) -> None:
        self.path = path
        self._held = False

    def _read_pid(self) -> int | None:
        try:
            with open(self.path, encoding="ascii") as fh:
                return int(fh.read().split()[0])
        except (FileNotFoundError, ValueError, IndexError):
            return None

    def acquire(self) -> None:
        owner = self._read_pid()
        if owner is not None and owner != os.getpid() and _alive(owner):
            raise SystemExit(
                f"another build already holds {self.path} (pid {owner}); "
                f"wait for it, or remove the lock if that process is truly gone"
            )
        os.makedirs(os.path.dirname(self.path) or ".", exist_ok=True)
        with open(self.path, "w", encoding="ascii") as fh:
            fh.write(f"{os.getpid()}\n")
        self._held = True

    def release(self) -> None:
        # Only remove a lock we still own: a taken-over stale lock now records *our* pid, and we
        # must not delete a lock a different live build rewrote in the meantime.
        if self._held and self._read_pid() == os.getpid():
            try:
                os.remove(self.path)
            except FileNotFoundError:
                pass
        self._held = False

    def __enter__(self) -> RunLock:
        self.acquire()
        return self

    def __exit__(self, *_exc: object) -> None:
        self.release()


__all__ = ["RunLock"]

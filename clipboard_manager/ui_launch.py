"""Single-instance guard for the standalone history window.

The history window runs as its own process (Tk needs its own main loop), and
both the tray menu and the global hotkey spawn it. Without a guard, every
hotkey press or menu click launches another window process.

The guard is a small pidfile in the data directory: the running UI process
writes its PID there on start and removes it on exit. A later launch checks
the pidfile and skips spawning when that PID is still alive. A stale pidfile
(crashed process) is overwritten by the next launch.

No locking across platforms is needed: the worst race (two launches in the
same instant) produces two windows, never a stuck guard.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

PIDFILE_NAME = "ui.pid"


def _pid_alive(pid: int) -> bool:
    if pid <= 0:
        return False
    if sys.platform == "win32":
        import ctypes

        kernel32 = ctypes.windll.kernel32
        synchronize = 0x00100000
        handle = kernel32.OpenProcess(synchronize, False, pid)
        if not handle:
            return False
        kernel32.CloseHandle(handle)
        return True
    try:
        os.kill(pid, 0)
    except OSError:
        return False
    return True


def ui_already_running(data_dir: str | Path) -> bool:
    """True when a previously launched UI process is still alive."""
    pidfile = Path(data_dir) / PIDFILE_NAME
    try:
        pid = int(pidfile.read_text().strip())
    except (OSError, ValueError):
        return False
    return _pid_alive(pid)


def claim_ui_instance(data_dir: str | Path, pid: int | None = None) -> bool:
    """Record this process as the running UI. False if one is already alive."""
    if ui_already_running(data_dir):
        return False
    pidfile = Path(data_dir) / PIDFILE_NAME
    pidfile.parent.mkdir(parents=True, exist_ok=True)
    pidfile.write_text(str(pid if pid is not None else os.getpid()))
    return True


def release_ui_instance(data_dir: str | Path, pid: int | None = None) -> None:
    """Remove the pidfile, but only if it is still ours."""
    pidfile = Path(data_dir) / PIDFILE_NAME
    try:
        recorded = int(pidfile.read_text().strip())
    except (OSError, ValueError):
        return
    if recorded == (pid if pid is not None else os.getpid()):
        pidfile.unlink(missing_ok=True)

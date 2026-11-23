"""Cross-process coordination for image-file creation and cleanup."""

from __future__ import annotations

import os
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator


@contextmanager
def image_files_lock(images_dir: str | Path) -> Iterator[None]:
    """Exclusively lock image-file mutations for one application's data directory.

    Capture must hold this lock from before creating the PNG until its SQLite
    row is committed. Orphan cleanup must hold the same lock across its final
    database re-check and file deletion. The OS releases the lock if a process
    exits or crashes, so no stale-PID recovery is needed.
    """
    images_path = Path(images_dir)
    lock_path = images_path.parent / ".image-files.lock"
    lock_path.parent.mkdir(parents=True, exist_ok=True)

    with lock_path.open("a+b") as lock_file:
        lock_file.seek(0, os.SEEK_END)
        if lock_file.tell() == 0:
            lock_file.write(b"\\0")
            lock_file.flush()

        if os.name == "nt":
            import msvcrt

            # LK_LOCK gives up after a bounded retry period. Retry until the
            # byte-range lock is acquired; opening the file has already
            # established that the path itself is accessible.
            while True:
                lock_file.seek(0)
                try:
                    msvcrt.locking(lock_file.fileno(), msvcrt.LK_NBLCK, 1)
                    break
                except OSError:
                    time.sleep(0.05)
            try:
                yield
            finally:
                lock_file.seek(0)
                msvcrt.locking(lock_file.fileno(), msvcrt.LK_UNLCK, 1)
        else:
            import fcntl

            fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX)
            try:
                yield
            finally:
                fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)

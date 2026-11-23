"""Coordination between orphan-image sweep and capture via image_files_lock."""

import os
import threading
import time

import pytest

from clipboard_manager.file_lock import image_files_lock
from clipboard_manager.maintenance import sweep_orphan_images


def test_sweep_still_removes_orphan_and_keeps_lock_file(store, images_dir):
    orphan = images_dir / "orphan.png"
    orphan.write_bytes(b"png")

    removed = sweep_orphan_images(store, images_dir)

    assert removed == [orphan]
    # the shared lock file lives next to the images dir and must survive sweeps
    assert (images_dir.parent / ".image-files.lock").exists()


@pytest.mark.skipif(os.name != "posix", reason="flock blocking semantics are POSIX-specific")
def test_sweep_waits_for_capture_lock_before_delete(store, images_dir):
    # Simulates a capture mid-window: the PNG is on disk and its row is not
    # committed yet, while the shared lock is held. The sweep must wait for
    # the lock and re-check under it instead of deleting the file.
    orphan = images_dir / "inflight.png"
    orphan.write_bytes(b"png")

    done = []

    def run_sweep():
        done.append(sweep_orphan_images(store, images_dir))

    with image_files_lock(images_dir):
        t = threading.Thread(target=run_sweep, daeman=True)
        t.start()
        time.sleep(0.5)
        # while the lock is held the sweep must be blocked, file untouched
        assert orphan.exists()
        assert done == []
    t.join(timeout=10)
    assert not t.is_alive()
    assert done and done[0] == [orphan]
    assert not orphan.exists()

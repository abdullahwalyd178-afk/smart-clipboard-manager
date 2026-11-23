from __future__ import annotations

import subprocess
import sys
import threading
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from clipboard_manager.image_cleanup import (
    clear_unpinned,
    delete_item,
    purge_and_enforce,
)


def _add_image(store, images_dir: Path):
    image_path = images_dir / "shared.png"
    image_path.write_bytes(b"test image")
    item, created = store.add_image(\n        str(image_path),\n        digest="shared-image",\n        created_at=(datetime.now(timezone.utc) - timedelta(days=2)).isoformat(timespec="seconds"),\n    )
    assert created
    return item, image_path


@pytest.mark.parametrize("operation", ["delete", "clear", "purge"])
def test_image_cleanup_waits_for_capture_lock_on_all_platforms(
    store, images_dir, operation
):
    """A cleanup process must wait while capture owns the shared image lock."""
    item, image_path = _add_image(store, images_dir)

    def cleanup():
        if operation == "delete":
            return delete_item(store, item.id, images_dir)
        if operation == "clear":
            return clear_unpinned(store, images_dir)
        return purge_and_enforce(
            store, images_dir, retention_days=1, max_items=0
        )

    holder = subprocess.Popen(
        [
            sys.executable,
            "-c",
            "import sys, time\n"
            "from clipboard_manager.file_lock import image_files_lock\n"
            "with image_files_lock(sys.argv[1]):\n"
            "    print('LOCKED', flush=True)\n"
            "    time.sleep(30)\n",
            str(images_dir),
        ],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )

    worker = None
    try:
        assert holder.stdout.readline().strip() == "LOCKED"

        started = threading.Event()

        def run_cleanup():
            started.set()
            cleanup()

        worker = threading.Thread(target=run_cleanup, daemon=True)
        worker.start()
        assert started.wait(timeout=2)
        time.sleep(0.25)

        # This assertion is platform-independent: the subprocess still owns
        # the OS lock, so cleanup must not mutate SQLite or unlink the image.
        assert worker.is_alive()
        assert store.get(item.id) is not None
        assert image_path.exists()
    finally:
        holder.terminate()
        holder.wait(timeout=5)

    assert worker is not None
    worker.join(timeout=5)
    assert not worker.is_alive()
    assert store.get(item.id) is None
    assert not image_path.exists()

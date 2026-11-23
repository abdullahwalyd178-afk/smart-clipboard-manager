"""Storage maintenance: orphan image cleanup.

An orphan is a PNG in the images directory that no database row references.
They can appear when a capture was interrupted after the file was written but
before the row was inserted, or after an older build deleted rows without
their files. ``sweep_orphan_images`` removes them; referenced files are never
touched.
"""

from __future__ import annotations

import logging
import time
from pathlib import Path

from .file_lock import image_files_lock
from .storage import ClipboardStore

logger = logging.getLogger(__name__)


def sweep_orphan_images(
    store: ClipboardStore,
    images_dir: str | Path,
    min_age_seconds: float = 0.0,
) -> list[Path]:
    """Delete image files on disk that no stored item references.

    Returns the list of removed files (may be empty). Only files inside
    ``images_dir`` with an image extension are candidates - anything else in
    the directory is left alone.

    ``min_age_seconds`` is a race guard: a capture writes the PNG first and
    inserts the database row a moment later, so a periodic sweep could meet a
    file whose row does not exist yet. Files younger than this many seconds
    (by modification time) are skipped and re-examined on the next sweep.

    The definitive race guard is the shared ``image_files_lock``: capture
    holds it from before the PNG write until its database row is committed,
    so while the sweep holds the same lock no capture can be between
    "file written" and "row inserted". The sweep only takes the lock around
    each candidate's final database re-check and deletion; the age scan
    itself runs lock-free.
    """
    directory = Path(images_dir)
    if not directory.is_dir():
        return []
    referenced = store.all_image_paths()
    removed: list[Path] = []
    cutoff = time.time() - min_age_seconds
    for path in sorted(directory.iterdir()):
        if not path.is_file() or path.suffix.lower() != ".png":
            continue
        try:
            key = str(path)
        except OSError:
            continue
        if key in referenced:
            continue
        try:
            if path.stat().st_mtime > cutoff:
                continue  # maybe an in-flight capture; check again next sweep
        except OSError:
            continue
        # Definitive race guard after the grace window: re-check this exact
        # path against the database and delete it while holding the same
        # lock capture holds across "write PNG + insert row". A capture that
        # is anywhere inside that window either finished before we acquired
        # the lock (the re-check sees its row) or starts after we release it
        # (its file is not deleted here). The earlier age scan stayed
        # lock-free so a long sweep never stalls capture.
        with image_files_lock(directory):
            if store.image_path_referenced(key):
                continue
            try:
                path.unlink()
                removed.append(path)
            except OSError:
                logger.warning("could not remove orphan image %s", path)
    if removed:
        logger.info("removed %d orphan image(s)", len(removed))
    return removed

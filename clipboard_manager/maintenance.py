"""Storage maintenance: orphan image cleanup.

An orphan is a PNG in the images directory that no database row references.
They can appear when a capture was interrupted after the file was written but
before the row was inserted, or after an older build deleted rows without
their files. ``sweep_orphan_images`` removes them; referenced files are never
touched.
"""

from __future__ import annotations

import logging
from pathlib import Path

from .storage import ClipboardStore

logger = logging.getLogger(__name__)


def sweep_orphan_images(store: ClipboardStore, images_dir: str | Path) -> list[Path]:
    """Delete image files on disk that no stored item references.

    Returns the list of removed files (may be empty). Only files inside
    ``images_dir`` with an image extension are candidates - anything else in
    the directory is left alone.
    """
    directory = Path(images_dir)
    if not directory.is_dir():
        return []
    referenced = store.all_image_paths()
    removed: list[Path] = []
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
            path.unlink()
            removed.append(path)
        except OSError:
            logger.warning("could not remove orphan image %s", path)
    if removed:
        logger.info("removed %d orphan image(s)", len(removed))
    return removed

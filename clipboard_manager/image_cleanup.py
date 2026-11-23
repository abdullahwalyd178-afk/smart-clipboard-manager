"""Lock-coordinated deletion of clipboard image records and their files."""

from __future__ import annotations

import logging
from pathlib import Path

from .file_lock import image_files_lock
from .storage import ClipboardStore

logger = logging.getLogger(__name__)


def _unlink_images(store: ClipboardStore, items) -> None:
    for item in items:
        if item.image_path and not store.image_path_referenced(item.image_path):
            try:
                Path(item.image_path).unlink(missing_ok=True)
            except OSError:
                logger.warning(
                    "Could not remove clipboard image file: %s",
                    item.image_path,
                    exc_info=True,
                )


def purge_and_enforce(
    store: ClipboardStore,
    images_dir: str | Path,
    retention_days: int,
    max_items: int,
) -> list:
    """Delete expired/over-limit rows and their images atomically vs. capture."""
    with image_files_lock(images_dir):
        removed = store.purge_expired(retention_days)
        removed.extend(store.enforce_max_items(max_items))
        _unlink_images(store, removed)
    return removed


def delete_item(
    store: ClipboardStore, item_id: int, images_dir: str | Path
):
    """Delete one history row and its image under the shared capture lock."""
    with image_files_lock(images_dir):
        removed = store.delete(item_id)
        if removed is not None:
            _unlink_images(store, [removed])
    return removed


def clear_unpinned(
    store: ClipboardStore, images_dir: str | Path
) -> list:
    """Delete unpinned rows and their images under the shared capture lock."""
    with image_files_lock(images_dir):
        removed = store.clear_unpinned()
        _unlink_images(removed)
    return removed

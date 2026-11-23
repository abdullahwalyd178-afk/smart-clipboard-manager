"""Clipboard monitoring with non-blocking OCR.

Clipboard polling and OCR use separate daemon workers. A slow OCR engine can
therefore never stall capture of subsequent clipboard changes.
"""

from __future__ import annotations

import logging
import queue
import threading
from pathlib import Path
from typing import Callable

from .models import ClipboardItem
from .storage import ClipboardStore

logger = logging.getLogger(__name__)
OCR_QUEUE_MAXSIZE = 100
_STOP_OCR = object()


class ClipboardProvider:
    """Interface over the real OS clipboard (see PyperclipPILProvider)."""

    def get_text(self) -> str | None:
        raise NotImplementedError

    def get_image_png_bytes(self) -> bytes | None:
        raise NotImplementedError

    def set_text(self, text: str) -> None:
        raise NotImplementedError


class PyperclipPILProvider(ClipboardProvider):
    """Real clipboard access: pyperclip for text, PIL ImageGrab for images."""

    def get_text(self) -> str | None:
        import pyperclip

        try:
            value = pyperclip.paste()
        except Exception:
            logger.debug("Unable to read text clipboard", exc_info=True)
            return None
        return value if isinstance(value, str) and value else None

    def get_image_png_bytes(self) -> bytes | None:
        import io

        from PIL import Image, ImageGrab

        try:
            data = ImageGrab.grabclipboard()
        except Exception:
            logger.debug("Unable to read image clipboard", exc_info=True)
            return None
        if isinstance(data, Image.Image):
            buf = io.BytesIO()
            data.convert("RGB").save(buf, format="PNG")
            return buf.getvalue()
        if isinstance(data, list) and data:
            path = Path(data[0])
            if path.is_file():
                try:
                    with Image.open(path) as img:
                        buf = io.BytesIO()
                        img.convert("RGB").save(buf, format="PNG")
                        return buf.getvalue()
                except (OSError, ValueError):
                    logger.warning("Clipboard image file could not be read: %s", path)
        return None

    def set_text(self, text: str) -> None:
        import pyperclip

        pyperclip.copy(text)


class ClipboardWatcher:
    def __init__(
        self,
        store: ClipboardStore,
        provider: ClipboardProvider,
        images_dir: str | Path,
        ocr_engine=None,
        poll_interval: float = 0.5,
        copy_ocr_result_to_clipboard: bool = True,
        on_new_item: Callable[[ClipboardItem], None] | None = None,
        max_items: int = 500,
    ):
        if poll_interval <= 0:
            raise ValueError("poll_interval must be greater than zero")
        if max_items < 0:
            raise ValueError("max_items cannot be negative")

        self.store = store
        self.provider = provider
        self.images_dir = Path(images_dir)
        self.ocr_engine = ocr_engine
        self.poll_interval = poll_interval
        self.copy_ocr_result_to_clipboard = copy_ocr_result_to_clipboard
        self.on_new_item = on_new_item
        self.max_items = max_items

        self._last_hash: str | None = None
        self._hash_lock = threading.Lock()
        self._pause_event = threading.Event()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._ocr_thread: threading.Thread | None = None
        self._ocr_queue: queue.Queue = queue.Queue(maxsize=OCR_QUEUE_MAXSIZE)
        self._ocr_shutdown_requested = False
        self._ocr_restart_requested = False
        self._lifecycle_lock = threading.Lock()

    @property
    def paused(self) -> bool:
        return self._pause_event.is_set()

    def pause(self) -> None:
        self._pause_event.set()

    def resume(self) -> None:
        self._pause_event.clear()

    def _ensure_ocr_worker(self) -> None:
        if self.ocr_engine is None:
            return
        with self._lifecycle_lock:
            if self._ocr_thread is not None and self._ocr_thread.is_alive():
                return
            self._ocr_shutdown_requested = False
            self._ocr_thread = threading.Thread(
                target=self._ocr_loop, args=(self._ocr_queue,),
                name="clipboard-ocr", daemon=True
            )
            self._ocr_thread.start()

    def start(self) -> None:
        with self._lifecycle_lock:
            if self._thread is not None and self._thread.is_alive():
                return
            self._stop.clear()
            if (
                self._ocr_thread is not None
                and self._ocr_thread.is_alive()
                and self._ocr_shutdown_requested
            ):
                # A previous stop timed out while OCR was busy. The worker
                # will consume its sentinel after the active task; ask it to
                # hand the same queue to a replacement worker before exiting.
                self._ocr_restart_requested = True
            self._thread = threading.Thread(
                target=self._run, name="clipboard-watcher", daemon=True
            )
            self._thread.start()
        self._ensure_ocr_worker()

    def stop(self, timeout: float = 5.0) -> bool:
        """Stop polling and drain OCR work; False means a worker is still busy."""
        self._stop.set()
        with self._lifecycle_lock:
            thread = self._thread
        if thread is not None:
            thread.join(timeout=max(0.0, timeout))
            if thread.is_alive():
                logger.warning("Clipboard watcher did not stop within %.1f seconds", timeout)
                return False
            with self._lifecycle_lock:
                if self._thread is thread:
                    self._thread = None

        with self._lifecycle_lock:
            ocr_thread = self._ocr_thread
            if ocr_thread is not None and ocr_thread.is_alive() and not self._ocr_shutdown_requested:
                self._ocr_shutdown_requested = True
                try:
                    self._ocr_queue.put(_STOP_OCR, timeout=max(0.0, timeout))
                except queue.Full:
                    self._ocr_shutdown_requested = False
                    logger.warning("OCR queue is full; shutdown sentinel could not be queued")
                    return False

        if ocr_thread is not None:
            ocr_thread.join(timeout=max(0.0, timeout))
            if ocr_thread.is_alive():
                logger.warning("OCR worker did not stop within %.1f seconds", timeout)
                return False
            with self._lifecycle_lock:
                if self._ocr_thread is ocr_thread:
                    self._ocr_thread = None
                    self._ocr_shutdown_requested = False
                elif self._ocr_thread is not None and self._ocr_thread.is_alive():
                    # A concurrent restart handed off to a replacement worker.
                    # Do not report a clean shutdown while that worker uses SQLite.
                    logger.warning("OCR worker restarted while shutdown was waiting")
                    return False
                else:
                    self._ocr_thread = None
                    self._ocr_shutdown_requested = False
        return True

    def _run(self) -> None:
        while not self._stop.is_set():
            try:
                self.poll_once()
            except Exception:
                logger.exception("Unexpected clipboard polling failure")
            self._stop.wait(self.poll_interval)

    def _ocr_loop(self, task_queue: queue.Queue) -> None:
        while True:
            task = task_queue.get()
            try:
                if task is _STOP_OCR:
                    with self._lifecycle_lock:
                        if self._ocr_restart_requested and task_queue is self._ocr_queue:
                            self._ocr_restart_requested = False
                            self._ocr_shutdown_requested = False
                            replacement = threading.Thread(
                                target=self._ocr_loop,
                                args=(task_queue,),
                                name="clipboard-ocr",
                                daemon=True,
                            )
                            self._ocr_thread = replacement
                            replacement.start()
                        elif self._ocr_thread is threading.current_thread():
                            # Publish the worker as stopped before returning.
                            # A concurrent start can then safely create a new
                            # worker instead of enqueueing behind a dead sentinel.
                            self._ocr_thread = None
                            self._ocr_shutdown_requested = False
                    return
                item_id, image_path, digest = task
                self._process_ocr(item_id, image_path, digest)
            except Exception:
                logger.exception("Unexpected OCR worker failure")
            finally:
                task_queue.task_done()

    def _process_ocr(self, item_id: int, image_path: str, digest: str) -> None:
        # An item may have expired or been evicted while waiting in the queue.
        if self.store.get(item_id) is None:
            return
        try:
            ocr_text = self.ocr_engine.extract_text(image_path)
        except Exception:
            logger.exception("OCR failed for clipboard image %s", image_path)
            return
        if not ocr_text or self.store.get(item_id) is None:
            return

        self.store.set_ocr_text(item_id, ocr_text)
        if self.copy_ocr_result_to_clipboard and self._current_clipboard_hash() == digest:
            try:
                self.provider.set_text(ocr_text)
                with self._hash_lock:
                    self._last_hash = ClipboardItem.hash_text(ocr_text)
            except Exception:
                logger.warning("Could not copy OCR result to clipboard", exc_info=True)

    def _apply_item_limit(self) -> None:
        if self.max_items <= 0:
            return
        removed = self.store.enforce_max_items(self.max_items)
        for item in removed:
            if item.image_path:
                try:
                    Path(item.image_path).unlink(missing_ok=True)
                except OSError:
                    logger.warning("Could not remove evicted clipboard image: %s", item.image_path)

    def poll_once(self) -> ClipboardItem | None:
        """Check the clipboard once. Returns the new item, or None."""
        if self.paused:
            return None

        text = self.provider.get_text()
        if text:
            return self._capture_text(text)

        png = self.provider.get_image_png_bytes()
        if png:
            return self._capture_image(png)
        return None

    def _capture_text(self, text: str) -> ClipboardItem | None:
        digest = ClipboardItem.hash_text(text)
        with self._hash_lock:
            if digest == self._last_hash:
                return None
            # Commit the deduplication hash only after persistence succeeds.
            # Keep the lock across the write so concurrent pollers cannot race.
            item, is_new = self.store.add_text(text)
            self._last_hash = digest
        if not is_new:
            return None
        self._apply_item_limit()
        if self.on_new_item:
            self.on_new_item(item)
        return item

    def _current_clipboard_hash(self) -> str | None:
        """Hash of whatever is on the clipboard right now (text or image)."""
        try:
            text = self.provider.get_text()
            if text:
                return ClipboardItem.hash_text(text)
            png = self.provider.get_image_png_bytes()
            if png:
                return ClipboardItem.hash_bytes(png)
        except Exception:
            logger.debug("Could not verify clipboard after OCR", exc_info=True)
        return None

    def _capture_image(self, png: bytes) -> ClipboardItem | None:
        digest = ClipboardItem.hash_bytes(png)
        with self._hash_lock:
            if digest == self._last_hash:
                return None

            self.images_dir.mkdir(parents=True, exist_ok=True)
            image_path = self.images_dir / f"{digest[:16]}.png"
            created_image_file = False
            if not image_path.exists():
                temporary_path = image_path.with_suffix(".png.tmp")
                try:
                    temporary_path.write_bytes(png)
                    temporary_path.replace(image_path)
                    created_image_file = True
                finally:
                    temporary_path.unlink(missing_ok=True)

            # Do not mark this digest as seen until SQLite confirms the write.
            try:
                item, is_new = self.store.add_image(str(image_path), digest)
            except Exception:
                if created_image_file:
                    try:
                        # Another record may already reference the same digest.
                        existing = self.store.get_by_hash(digest)
                        if existing is None or existing.image_path != str(image_path):
                            image_path.unlink(missing_ok=True)
                    except Exception:
                        # If the database is unavailable, leave cleanup to the
                        # startup orphan-file maintenance rather than risk data loss.
                        logger.warning(
                            "Could not verify failed image persistence cleanup: %s",
                            image_path,
                            exc_info=True,
                        )
                raise
            self._last_hash = digest

        if not is_new:
            return None
        if self.ocr_engine is not None:
            self._ensure_ocr_worker()
            try:
                self._ocr_queue.put_nowait((item.id, str(image_path), digest))
            except queue.Full:
                # The clipboard item is already persisted; only its optional
                # OCR is skipped so image capture can never be back-pressured.
                logger.warning("OCR queue is full; skipping OCR for image %s", image_path)

        self._apply_item_limit()
        if self.on_new_item:
            self.on_new_item(item)
        return item

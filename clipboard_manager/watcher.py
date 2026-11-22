"""Clipboard monitoring loop.

The watcher polls the OS clipboard on a background thread. OCR runs on that
worker thread (never the tray/UI thread); polling resumes after OCR completes.
"""

from __future__ import annotations

import logging
import threading
from pathlib import Path
from typing import Callable

from .models import ClipboardItem
from .storage import ClipboardStore

logger = logging.getLogger(__name__)


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
        self._pause_event = threading.Event()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._lifecycle_lock = threading.Lock()

    @property
    def paused(self) -> bool:
        return self._pause_event.is_set()

    def pause(self) -> None:
        self._pause_event.set()

    def resume(self) -> None:
        self._pause_event.clear()

    def start(self) -> None:
        with self._lifecycle_lock:
            if self._thread is not None and self._thread.is_alive():
                return
            self._stop.clear()
            self._thread = threading.Thread(
                target=self._run, name="clipboard-watcher", daemon=True
            )
            self._thread.start()

    def stop(self, timeout: float = 5.0) -> bool:
        self._stop.set()
        with self._lifecycle_lock:
            thread = self._thread
        if thread is None:
            return True
        thread.join(timeout=max(0.0, timeout))
        if not thread.is_alive():
            with self._lifecycle_lock:
                if self._thread is thread:
                    self._thread = None
            return True
        logger.warning("Clipboard watcher did not stop within %.1f seconds", timeout)
        return False

    def _run(self) -> None:
        while not self._stop.is_set():
            try:
                self.poll_once()
            except Exception:
                logger.exception("Unexpected clipboard polling failure")
            self._stop.wait(self.poll_interval)

    def _apply_item_limit(self) -> None:
        if self.max_items <= 0:
            return
        removed = self.store.enforce_max_items(self.max_items)
        for item in removed:
            if item.image_path:
                try:
                    Path(item.image_path).unlink(missing_ok=True)
                except OSError:
                    logger.warning("Could not remove expired clipboard image: %s", item.image_path)

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
        if digest == self._last_hash:
            return None
        self._last_hash = digest
        item, is_new = self.store.add_text(text)
        if not is_new:
            return None
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
        if digest == self._last_hash:
            return None
        self._last_hash = digest

        self.images_dir.mkdir(parents=True, exist_ok=True)
        image_path = self.images_dir / f"{digest[:16]}.png"
        if not image_path.exists():
            temporary_path = image_path.with_suffix(".png.tmp")
            try:
                temporary_path.write_bytes(png)
                temporary_path.replace(image_path)
            finally:
                temporary_path.unlink(missing_ok=True)

        item, is_new = self.store.add_image(str(image_path), digest)
        if not is_new:
            return None
        # Enforce the cap before OCR, which may take several seconds or longer.
        self._apply_item_limit()

        if self.ocr_engine is not None:
            try:
                ocr_text = self.ocr_engine.extract_text(str(image_path))
            except Exception:
                logger.exception("OCR failed for clipboard image %s", image_path)
                ocr_text = ""
            if ocr_text:
                self.store.set_ocr_text(item.id, ocr_text)
                item.ocr_text = ocr_text
                if self.copy_ocr_result_to_clipboard and self._current_clipboard_hash() == digest:
                    try:
                        self.provider.set_text(ocr_text)
                        self._last_hash = ClipboardItem.hash_text(ocr_text)
                    except Exception:
                        logger.warning("Could not copy OCR result to clipboard", exc_info=True)

        self._apply_item_limit()
        if self.on_new_item:
            self.on_new_item(item)
        return item

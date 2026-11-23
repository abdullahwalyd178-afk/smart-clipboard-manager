"""Clipboard monitoring loop.

The watcher polls the clipboard on a background thread. ``poll_once`` does one
check and is fully synchronous (including OCR) so tests can drive it directly;
the production loop just calls it repeatedly, so a slow OCR pass never touches
the UI thread - it only delays the next poll.
"""

from __future__ import annotations

import threading
import time
from pathlib import Path
from typing import Callable

from .file_lock import image_files_lock
from .models import ClipboardItem
from .storage import ClipboardStore


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
            return None
        return value if isinstance(value, str) and value else None

    def get_image_png_bytes(self) -> bytes | None:
        import io

        from PIL import Image, ImageGrab

        try:
            data = ImageGrab.grabclipboard()
        except Exception:
            return None
        if isinstance(data, Image.Image):
            buf = io.BytesIO()
            data.convert("RGB").save(buf, format="PNG")
            return buf.getvalue()
        if isinstance(data, list) and data:  # clipboard held file path(s)
            path = Path(data[0])
            if path.is_file():
                with Image.open(path) as img:
                    buf = io.BytesIO()
                    img.convert("RGB").save(buf, format="PNG")
                    return buf.getvalue()
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
        max_items: int = 0,
    ):
        self.store = store
        self.provider = provider
        self.images_dir = Path(images_dir)
        self.ocr_engine = ocr_engine
        self.poll_interval = poll_interval
        self.copy_ocr_result_to_clipboard = copy_ocr_result_to_clipboard
        self.on_new_item = on_new_item
        self.max_items = max_items

        self._hash_lock = threading.Lock()
        self._last_hash: str | None = None
        self._paused = False
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    # -- control -----------------------------------------------------------

    @property
    def paused(self) -> bool:
        return self._paused

    def pause(self) -> None:
        self._paused = True

    def resume(self) -> None:
        self._paused = False

    def start(self) -> None:
        if self._thread is not None:
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, name="clipboard-watcher", daemon=True)
        self._thread.start()

    def stop(self, timeout: float = 5.0) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=timeout)
            self._thread = None

    def _run(self) -> None:
        while not self._stop.is_set():
            try:
                self.poll_once()
            except Exception:
                pass  # a bad clipboard read or OCR failure must never kill the loop
            self._stop.wait(self.poll_interval)

    # -- one polling step (synchronous, test-friendly) ---------------------

    def poll_once(self) -> ClipboardItem | None:
        """Check the clipboard once. Returns the new item, or None."""
        if self._paused:
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
            # Commit the deduplication hash only after SQLite confirms the write.
            item, is_new = self.store.add_text(text)
            self._last_hash = digest
        if not is_new:
            return None
        self._apply_item_limit()
        if self.on_new_item:
            self.on_new_item(item)
        return item

    def _apply_item_limit(self) -> None:
        if self.max_items <= 0:
            return
        with image_files_lock(self.images_dir):
            removed = self.store.enforce_max_items(self.max_items)
            for item in removed:
                if item.image_path and not self.store.image_path_referenced(item.image_path):
                    try:
                        Path(item.image_path).unlink(missing_ok=True)
                    except OSError:
                        pass

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
            pass
        return None

    def _capture_image(self, png: bytes) -> ClipboardItem | None:
        digest = ClipboardItem.hash_bytes(png)
        # Coordinate PNG creation + row insertion with every cleanup/sweep path.
        with image_files_lock(self.images_dir):
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

                try:
                    item, is_new = self.store.add_image(str(image_path), digest)
                except Exception:
                    if created_image_file:
                        try:
                            if not self.store.image_path_referenced(str(image_path)):
                                image_path.unlink(missing_ok=True)
                        except Exception:
                            # Preserve the file if the database cannot establish
                            # whether another row still references it.
                            pass
                    raise
                self._last_hash = digest

        if not is_new:
            return None

        if self.ocr_engine is not None:
            try:
                ocr_text = self.ocr_engine.extract_text(str(image_path))
            except Exception:
                ocr_text = ""
            # Empty output is a completed attempt, not an absent/pending result.
            self.store.set_ocr_text(item.id, ocr_text)
            item.ocr_text = ocr_text
            if ocr_text and self.copy_ocr_result_to_clipboard:
                # OCR can take seconds; never overwrite a newer user copy.
                if self._current_clipboard_hash() == digest:
                    try:
                        self.provider.set_text(ocr_text)
                        with self._hash_lock:
                            self._last_hash = ClipboardItem.hash_text(ocr_text)
                    except Exception:
                        pass

        self._apply_item_limit()
        if self.on_new_item:
            self.on_new_item(item)
        return item

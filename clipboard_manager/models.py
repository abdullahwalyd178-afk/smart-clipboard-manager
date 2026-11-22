"""Data model for clipboard history items."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import datetime, timezone

TEXT = "text"
IMAGE = "image"
KINDS = (TEXT, IMAGE)


@dataclass
class ClipboardItem:
    """One clipboard history entry.

    Text items carry their content in ``text``. Image items carry a path to a
    PNG file on disk in ``image_path`` plus (optionally) ``ocr_text`` once OCR
    has run. ``created_at`` is an ISO-8601 UTC timestamp; because every value
    uses the same format, lexicographic comparison is also chronological.
    """

    id: int | None
    kind: str
    content_hash: str
    text: str | None = None
    image_path: str | None = None
    ocr_text: str | None = None
    pinned: bool = False
    created_at: str = ""

    @staticmethod
    def utcnow_iso() -> str:
        return datetime.now(timezone.utc).isoformat(timespec="seconds")

    @staticmethod
    def hash_text(value: str) -> str:
        return hashlib.sha256(value.encode("utf-8")).hexdigest()

    @staticmethod
    def hash_bytes(value: bytes) -> str:
        return hashlib.sha256(value).hexdigest()

    def preview(self, max_len: int = 60) -> str:
        """Short single-line label for menus and listings."""
        source = self.text if self.kind == TEXT else (self.ocr_text or "[image]")
        source = (source or "").replace("\n", " ").strip()
        if len(source) > max_len:
            source = source[: max_len - 1] + "…"
        pin = "📌 " if self.pinned else ""
        return f"{pin}{source}"

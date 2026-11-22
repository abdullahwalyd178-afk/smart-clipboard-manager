"""Data model for clipboard history items."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import datetime, timezone

TEXT = "text"
IMAGE = "image"
KINDS = (TEXT, IMAGE)

# OCR status values stored on image items.
OCR_PENDING = "pending"
OCR_DONE = "done"
OCR_FAILED = "failed"


@dataclass
class ClipboardItem:
    """One clipboard history entry.

    Text items carry their content in ``text``. Image items carry a path to a
    PNG file on disk in ``image_path`` plus (optionally) ``ocr_text`` once OCR
    has run. ``created_at`` is an ISO-8601 UTC timestamp; because every value
    uses the same format, lexicographic comparison is also chronological.

    ``favorite`` is a user flag independent from ``pinned``: pinned means
    "never auto-delete", favorite means "marked as important" for filtering.
    ``tags`` is a comma-separated list of user-chosen labels.
    ``ocr_status`` tracks OCR progress for image items: pending / done / failed.
    """

    id: int | None
    kind: str
    content_hash: str
    text: str | None = None
    image_path: str | None = None
    ocr_text: str | None = None
    pinned: bool = False
    created_at: str = ""
    favorite: bool = False
    tags: str = ""
    ocr_status: str | None = None

    @staticmethod
    def utcnow_iso() -> str:
        return datetime.now(timezone.utc).isoformat(timespec="seconds")

    @staticmethod
    def hash_text(value: str) -> str:
        return hashlib.sha256(value.encode("utf-8")).hexdigest()

    @staticmethod
    def hash_bytes(value: bytes) -> str:
        return hashlib.sha256(value).hexdigest()

    def tag_list(self) -> list[str]:
        return [t.strip() for t in (self.tags or "").split(",") if t.strip()]

    def preview(self, max_len: int = 60) -> str:
        """Short single-line label for menus and listings."""
        source = self.text if self.kind == TEXT else (self.ocr_text or "[image]")
        source = (source or "").replace("\n", " ").strip()
        if len(source) > max_len:
            source = source[: max_len - 1] + "…"
        mark = "• " if self.pinned else ("★ " if self.favorite else "")
        return f"{mark}{source}"

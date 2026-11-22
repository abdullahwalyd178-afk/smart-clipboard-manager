"""Configuration for Smart Clipboard Manager.

Config lives as JSON next to the database in the per-user data directory.
Unknown keys in the JSON are ignored so newer configs never break older builds.
"""

from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass, field
from pathlib import Path

APP_NAME = "SmartClipboard"


def default_data_dir() -> Path:
    """Per-user data directory (Windows: %APPDATA%\\SmartClipboard)."""
    if os.name == "nt":
        base = os.environ.get("APPDATA") or str(Path.home() / "AppData" / "Roaming")
        return Path(base) / APP_NAME
    base = os.environ.get("XDG_DATA_HOME") or str(Path.home() / ".local" / "share")
    return Path(base) / APP_NAME.lower()


@dataclass
class Config:
    # Unpinned items older than this many days are deleted automatically.
    retention_days: int = 3
    # How often the clipboard is polled, in seconds.
    poll_interval_seconds: float = 0.5
    # OCR engine: "tesseract" (default), "easyocr" or "pix2tex".
    ocr_engine: str = "tesseract"
    # Tesseract language code(s), e.g. "eng" or "eng+ara" (ara needs ara.traineddata).
    ocr_language: str = "eng"
    # Tesseract executable name or full path.
    tesseract_cmd: str = "tesseract"
    # After OCR of a screenshot, put the extracted text on the clipboard
    # so it is immediately ready to paste.
    copy_ocr_result_to_clipboard: bool = True
    # Safety cap on stored items (oldest unpinned removed first). 0 = no cap.
    max_items: int = 500
    data_dir: str = field(default_factory=lambda: str(default_data_dir()))

    @property
    def db_path(self) -> Path:
        return Path(self.data_dir) / "history.db"

    @property
    def images_dir(self) -> Path:
        return Path(self.data_dir) / "images"

    @property
    def config_path(self) -> Path:
        return Path(self.data_dir) / "config.json"

    @classmethod
    def load(cls, path: str | Path | None = None) -> "Config":
        cfg = cls()
        p = Path(path) if path else cfg.config_path
        if p.exists():
            data = json.loads(p.read_text(encoding="utf-8"))
            for key, value in data.items():
                if hasattr(cfg, key):
                    setattr(cfg, key, value)
        return cfg

    def save(self, path: str | Path | None = None) -> Path:
        p = Path(path) if path else self.config_path
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(
            json.dumps(asdict(self), indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
        return p

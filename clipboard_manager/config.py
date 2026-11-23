"""Validated configuration for Smart Clipboard Manager."""

from __future__ import annotations

import json
import math
import os
from dataclasses import asdict, dataclass, field
from pathlib import Path

APP_NAME = "SmartClipboard"
OCR_ENGINES = {"tesseract", "easyocr", "pix2tex"}


def default_data_dir() -> Path:
    """Per-user data directory (Windows: %APPDATA%\\SmartClipboard)."""
    if os.name == "nt":
        base = os.environ.get("APPDATA") or str(Path.home() / "AppData" / "Roaming")
        return Path(base) / APP_NAME
    base = os.environ.get("XDG_DATA_HOME") or str(Path.home() / ".local" / "share")
    return Path(base) / APP_NAME.lower()


@dataclass
class Config:
    retention_days: int = 3
    poll_interval_seconds: float = 0.5
    ocr_engine: str = "tesseract"
    ocr_language: str = "eng"
    tesseract_cmd: str = "tesseract"
    copy_ocr_result_to_clipboard: bool = True
    # Maximum number of unpinned items. Pinned items are retained in addition.
    max_items: int = 500
    data_dir: str = field(default_factory=lambda: str(default_data_dir()))

    def __post_init__(self) -> None:
        self.validate()

    def validate(self) -> None:
        if isinstance(self.retention_days, bool) or not isinstance(self.retention_days, int):
            raise ValueError("retention_days must be a whole number")
        if self.retention_days < 0:
            raise ValueError("retention_days cannot be negative")
        if isinstance(self.max_items, bool) or not isinstance(self.max_items, int):
            raise ValueError("max_items must be a whole number")
        if self.max_items < 0:
            raise ValueError("max_items cannot be negative (use 0 for unlimited)")
        if isinstance(self.poll_interval_seconds, bool) or not isinstance(
            self.poll_interval_seconds, (int, float)
        ):
            raise ValueError("poll_interval_seconds must be a number")
        if not math.isfinite(self.poll_interval_seconds) or self.poll_interval_seconds <= 0:
            raise ValueError("poll_interval_seconds must be a finite number greater than zero")
        if not isinstance(self.ocr_engine, str) or self.ocr_engine not in OCR_ENGINES:
            raise ValueError(
                f"unknown ocr_engine {self.ocr_engine!r} "
                f"(choose one of: {', '.join(sorted(OCR_ENGINES))})"
            )
        if not isinstance(self.ocr_language, str) or not self.ocr_language.strip():
            raise ValueError("ocr_language cannot be empty")
        if not isinstance(self.tesseract_cmd, str) or not self.tesseract_cmd.strip():
            raise ValueError("tesseract_cmd cannot be empty")
        if not isinstance(self.copy_ocr_result_to_clipboard, bool):
            raise ValueError("copy_ocr_result_to_clipboard must be true or false")
        if not isinstance(self.data_dir, str) or not self.data_dir.strip():
            raise ValueError("data_dir cannot be empty")

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
        config_path = Path(path) if path else cfg.config_path
        if not config_path.exists():
            return cfg
        try:
            data = json.loads(config_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise ValueError(f"Could not read configuration file {config_path}: {exc}") from exc
        if not isinstance(data, dict):
            raise ValueError(f"Configuration file {config_path} must contain a JSON object")
        allowed = set(asdict(cfg))
        for key, value in data.items():
            if key in allowed:
                setattr(cfg, key, value)
        cfg.validate()
        return cfg

    def save(self, path: str | Path | None = None) -> Path:
        self.validate()
        config_path = Path(path) if path else self.config_path
        config_path.parent.mkdir(parents=True, exist_ok=True)
        config_path.write_text(
            json.dumps(asdict(self), indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
        return config_path

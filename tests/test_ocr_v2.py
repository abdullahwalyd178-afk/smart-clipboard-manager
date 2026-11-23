"""v0.2 OCR behavior: language validation, timeouts, preprocessing, tracking, retry."""

import shutil
import sys
from pathlib import Path

import pytest

from clipboard_manager.config import Config
from clipboard_manager.ocr import (
    TesseractEngine,
    TrackingEngine,
    preprocess_image,
    retry_ocr,
)
from clipboard_manager.storage import ClipboardStore

from test_ocr import render_text_image  # reuse the real-image renderer

HAVE_TESSERACT = shutil.which("tesseract") is not None


@pytest.mark.skipif(not HAVE_TESSERACT, reason="tesseract not installed")
def test_installed_languages_and_validation():
    engine = TesseractEngine(language="eng")
    langs = engine.installed_languages()
    assert "eng" in langs
    engine.validate_languages()  # eng is installed: no error
    missing = TesseractEngine(language="eng+zzz-nope")
    with pytest.raises(RuntimeError, match="zzz-nope"):
        missing.validate_languages()


def test_timeout_raises_clear_error(tmp_path):
    """A tesseract that never answers must not stall polling forever."""
    if sys.platform == "win32":
        pytest.skip("shell-script fake needs POSIX")
    fake = tmp_path / "tesseract"
    fake.write_text("#!/bin/sh\nsleep 30\n")
    fake.chmod(0o755)
    engine = TesseractEngine(cmd=str(fake), timeout_seconds=1)
    with pytest.raises(RuntimeError, match="timed out"):
        engine.extract_text(tmp_path / "x.png")


@pytest.mark.skipif(not HAVE_TESSERACT, reason="tesseract not installed")
def test_preprocess_upscales_small_images(tmp_path):
    src = render_text_image("preprocess me", tmp_path / "small.png")
    out = preprocess_image(src, tmp_path / "big.png")
    from PIL import Image

    with Image.open(src) as a, Image.open(out) as b:
        assert b.width > a.width  # small image was upscaled


class RecordingStore:
    """Minimal store double for TrackingEngine."""

    def __init__(self, item):
        self.item = item
        self.failed = []

    def get_by_image_path(self, path):
        return self.item if self.item.image_path == path else None

    def mark_ocr_failed(self, item_id):
        self.failed.append(item_id)

    def set_ocr_status(self, item_id, status):
        self.item.ocr_status = status

    def set_ocr_text(self, item_id, text):
        self.item.ocr_text = text
        self.item.ocr_status = "done"


class _Item:
    def __init__(self, path):
        self.id = 7
        self.image_path = path
        self.ocr_status = None


class ExplodingEngine:
    name = "boom"

    def available(self):
        return True

    def extract_text(self, path):
        raise RuntimeError("engine exploded")


class EmptyEngine:
    name = "empty"

    def available(self):
        return True

    def extract_text(self, path):
        return ""


def test_tracking_engine_marks_failure():
    item = _Item("/tmp/s.png")
    store = RecordingStore(item)
    engine = TrackingEngine(ExplodingEngine(), store)
    with pytest.raises(RuntimeError):
        engine.extract_text("/tmp/s.png")
    assert store.failed == [7]


def test_tracking_engine_empty_result_is_marked_done():
    item = _Item("/tmp/s.png")
    store = RecordingStore(item)
    result = TrackingEngine(EmptyEngine(), store).extract_text("/tmp/s.png")
    assert result == ""
    assert item.ocr_text == ""
    assert item.ocr_status == "done"


@pytest.mark.skipif(not HAVE_TESSERACT, reason="tesseract not installed")
def test_retry_ocr_end_to_end(tmp_path):
    store = ClipboardStore(tmp_path / "history.db")
    image = render_text_image("retry path works 42", tmp_path / "shot.png")
    item, _ = store.add_image(str(image), digest="0" * 64)
    store.mark_ocr_failed(item.id)

    cfg = Config(data_dir=str(tmp_path))
    text = retry_ocr(store, cfg, item.id)
    assert "retry" in text.lower()
    assert store.get(item.id).ocr_status == "done"
    store.close()


def test_retry_ocr_rejects_text_items(tmp_path):
    store = ClipboardStore(tmp_path / "history.db")
    item, _ = store.add_text("plain text")
    cfg = Config(data_dir=str(tmp_path))
    with pytest.raises(ValueError, match="image"):
        retry_ocr(store, cfg, item.id)
    store.close()

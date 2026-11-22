"""OCR engine tests.

The Tesseract test is a real end-to-end OCR run: it renders text into an image
and checks Tesseract actually reads it back. It is skipped when no tesseract
binary is installed. Fixture text is synthetic - never real clipboard data.
"""

import shutil
from pathlib import Path

import pytest
from PIL import Image, ImageDraw, ImageFont

from clipboard_manager.config import Config
from clipboard_manager.ocr import TesseractEngine, create_engine

FONT_CANDIDATES = [
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    "/usr/share/fonts/dejavu/DejaVuSans.ttf",
    "C:/Windows/Fonts/arial.ttf",
]


def render_text_image(text: str, path: Path) -> Path:
    font = None
    for candidate in FONT_CANDIDATES:
        if Path(candidate).exists():
            font = ImageFont.truetype(candidate, 48)
            break
    img = Image.new("RGB", (900, 160), "white")
    draw = ImageDraw.Draw(img)
    draw.text((30, 40), text, fill="black", font=font)
    img.save(path)
    return path


@pytest.mark.skipif(shutil.which("tesseract") is None, reason="tesseract not installed")
def test_tesseract_reads_rendered_text(tmp_path):
    image = render_text_image("hello smart clipboard 123", tmp_path / "sample.png")
    engine = TesseractEngine()
    assert engine.available()
    result = engine.extract_text(str(image)).lower()
    assert "hello" in result and "clipboard" in result


def test_config_rejects_unknown_engine_before_engine_creation(tmp_path):
    # Config validates engine names at construction, so invalid settings never
    # reach the engine factory or the application startup path.
    with pytest.raises(ValueError, match="unknown ocr_engine"):
        Config(ocr_engine="does-not-exist", data_dir=str(tmp_path))


def test_factory_reports_missing_tesseract(tmp_path):
    cfg = Config(
        ocr_engine="tesseract",
        tesseract_cmd="tesseract-that-does-not-exist",
        data_dir=str(tmp_path),
    )
    with pytest.raises(RuntimeError, match="not found"):
        create_engine(cfg)

"""OCR engines for screenshots and image clips.

Honest scope notes
------------------
- Tesseract (default) and EasyOCR read *printed text* well. Neither one truly
  parses mathematical notation - a photo of "∫ x² dx" comes back as garbled
  characters, not LaTeX.
- For real math equations, use the optional ``pix2tex`` engine (LaTeX-OCR),
  which is built for exactly that. It is a heavy optional dependency, so it is
  not installed by default.

Tesseract is invoked as a subprocess (no pytesseract dependency); install the
binary with ``winget install UB-Mannheim.TesseractOCR`` on Windows.
"""

from __future__ import annotations

import importlib.util
import shutil
import subprocess
from pathlib import Path


class OCREngine:
    """Interface: given an image file path, return extracted text."""

    name = "base"

    def available(self) -> bool:
        raise NotImplementedError

    def extract_text(self, image_path: str | Path) -> str:
        raise NotImplementedError


class TesseractEngine(OCREngine):
    name = "tesseract"

    def __init__(self, cmd: str = "tesseract", language: str = "eng"):
        self.cmd = cmd
        self.language = language

    def available(self) -> bool:
        return shutil.which(self.cmd) is not None

    def extract_text(self, image_path: str | Path) -> str:
        result = subprocess.run(
            [self.cmd, str(image_path), "stdout", "-l", self.language],
            capture_output=True,
            timeout=120,
        )
        if result.returncode != 0:
            raise RuntimeError(
                f"tesseract failed ({result.returncode}): "
                f"{result.stderr.decode('utf-8', 'replace').strip()}"
            )
        return result.stdout.decode("utf-8", "replace").strip()


class EasyOCREngine(OCREngine):
    """Optional engine; requires ``pip install easyocr`` (pulls PyTorch)."""

    name = "easyocr"

    def __init__(self, languages: tuple[str, ...] = ("en",)):
        self.languages = languages
        self._reader = None

    def available(self) -> bool:
        return importlib.util.find_spec("easyocr") is not None

    def _get_reader(self):
        if self._reader is None:
            import easyocr

            self._reader = easyocr.Reader(list(self.languages))
        return self._reader

    def extract_text(self, image_path: str | Path) -> str:
        lines = self._get_reader().readtext(str(image_path), detail=0)
        return "\n".join(lines).strip()


class Pix2TexEngine(OCREngine):
    """Optional LaTeX-OCR engine for math equations; requires ``pip install pix2tex``."""

    name = "pix2tex"

    def __init__(self):
        self._model = None

    def available(self) -> bool:
        return importlib.util.find_spec("pix2tex") is not None

    def _get_model(self):
        if self._model is None:
            from pix2tex.cli import LatexOCR

            self._model = LatexOCR()
        return self._model

    def extract_text(self, image_path: str | Path) -> str:
        from PIL import Image

        with Image.open(str(image_path)) as img:
            return self._get_model()(img).strip()


_ENGINES = {
    TesseractEngine.name: TesseractEngine,
    EasyOCREngine.name: EasyOCREngine,
    Pix2TexEngine.name: Pix2TexEngine,
}


def create_engine(config) -> OCREngine:
    """Build the configured OCR engine, or raise a helpful error."""
    cls = _ENGINES.get(config.ocr_engine)
    if cls is None:
        known = ", ".join(sorted(_ENGINES))
        raise ValueError(f"unknown ocr_engine {config.ocr_engine!r} (choose one of: {known})")
    if config.ocr_engine == TesseractEngine.name:
        engine = cls(cmd=config.tesseract_cmd, language=config.ocr_language)
    else:
        engine = cls()
    if not engine.available():
        if config.ocr_engine == TesseractEngine.name:
            hint = "install it with: winget install UB-Mannheim.TesseractOCR"
        else:
            hint = f"install it with: pip install {config.ocr_engine}"
        raise RuntimeError(f"OCR engine {config.ocr_engine!r} not found - {hint}")
    return engine

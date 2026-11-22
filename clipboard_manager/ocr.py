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

Error-handling policy: engines raise on failure; the watcher catches and the
item keeps ``ocr_status = 'failed'`` so the UI can offer a retry. Tesseract
runs are bounded by a configurable timeout so a hung process can never stall
clipboard polling forever.
"""

from __future__ import annotations

import importlib.util
import logging
import shutil
import subprocess
import tempfile
from pathlib import Path

logger = logging.getLogger(__name__)


class OCREngine:
    """Interface: given an image file path, return extracted text."""

    name = "base"

    def available(self) -> bool:
        raise NotImplementedError

    def extract_text(self, image_path: str | Path) -> str:
        raise NotImplementedError


def preprocess_image(image_path: str | Path, out_path: str | Path) -> Path:
    """Improve a screenshot for OCR: grayscale, autocontrast, upscale small text.

    Returns the path of the processed image (``out_path``). Pure PIL, no extra
    dependencies. Upscaling small images noticeably helps Tesseract, including
    on Arabic text.
    """
    from PIL import Image, ImageOps

    with Image.open(str(image_path)) as img:
        gray = ImageOps.grayscale(img)
        gray = ImageOps.autocontrast(gray)
        w, h = gray.size
        if max(w, h) < 1500:
            scale = max(2, 1500 // max(w, h) + 1)
            gray = gray.resize((w * scale, h * scale), Image.LANCZOS)
        gray.save(str(out_path), format="PNG")
    return Path(out_path)


class TesseractEngine(OCREngine):
    name = "tesseract"

    def __init__(
        self,
        cmd: str = "tesseract",
        language: str = "eng",
        timeout_seconds: int = 60,
        preprocess: bool = False,
    ):
        self.cmd = cmd
        self.language = language
        self.timeout_seconds = timeout_seconds
        self.preprocess = preprocess

    def available(self) -> bool:
        return shutil.which(self.cmd) is not None

    def installed_languages(self) -> list[str]:
        """Languages reported by ``tesseract --list-langs`` (empty on failure)."""
        try:
            result = subprocess.run(
                [self.cmd, "--list-langs"], capture_output=True, timeout=30
            )
        except (OSError, subprocess.TimeoutExpired):
            return []
        if result.returncode != 0:
            return []
        lines = result.stdout.decode("utf-8", "replace").splitlines()
        return [
            line.strip()
            for line in lines[1:]
            if line.strip() and not line.startswith("List of")
        ]

    def missing_languages(self) -> list[str]:
        """Configured languages that Tesseract does not have data for."""
        installed = set(self.installed_languages())
        if not installed:
            return []  # cannot determine; do not block on an unreadable list
        requested = [lang.strip() for lang in self.language.split("+") if lang.strip()]
        return [lang for lang in requested if lang not in installed]

    def validate_languages(self) -> None:
        """Raise a helpful error when a configured language pack is missing."""
        missing = self.missing_languages()
        if missing:
            raise RuntimeError(
                f"tesseract has no data for language(s): {', '.join(missing)}. "
                "Install the language data (on Windows rerun the "
                "UB-Mannheim.TesseractOCR installer and pick the language), "
                "or change ocr_language in config.json."
            )

    def extract_text(self, image_path: str | Path) -> str:
        target = Path(image_path)
        temp_dir = None
        if self.preprocess:
            temp_dir = tempfile.TemporaryDirectory(prefix="smartclip-ocr-")
            target = preprocess_image(image_path, Path(temp_dir.name) / "pre.png")
        try:
            result = subprocess.run(
                [self.cmd, str(target), "stdout", "-l", self.language],
                capture_output=True,
                timeout=self.timeout_seconds,
            )
        except subprocess.TimeoutExpired as exc:
            raise RuntimeError(
                f"tesseract timed out after {self.timeout_seconds}s on {image_path}"
            ) from exc
        finally:
            if temp_dir is not None:
                temp_dir.cleanup()
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


class TrackingEngine(OCREngine):
    """Engine wrapper that records OCR status on the matching stored item.

    The watcher runs OCR after inserting an image item; this wrapper finds
    that item by its image path and marks it done/failed, so the UI can show
    status and offer a retry - without the watcher needing to know about the
    status column.
    """

    name = "tracking"

    def __init__(self, inner: OCREngine, store):
        self.inner = inner
        self.store = store

    def available(self) -> bool:
        return self.inner.available()

    def extract_text(self, image_path: str | Path) -> str:
        item = self.store.get_by_image_path(str(image_path))
        try:
            result = self.inner.extract_text(image_path)
        except Exception:
            if item is not None:
                self.store.mark_ocr_failed(item.id)
            raise
        if item is not None and not result.strip():
            # Empty output is not a failure, but it is not "done with text"
            # either; keep the status honest for the retry UI.
            self.store.set_ocr_status(item.id, None)
        return result


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
        engine = cls(
            cmd=config.tesseract_cmd,
            language=config.ocr_language,
            timeout_seconds=getattr(config, "ocr_timeout_seconds", 60),
            preprocess=getattr(config, "ocr_preprocess", False),
        )
        if engine.available():
            engine.validate_languages()
    else:
        engine = cls()
    if not engine.available():
        if config.ocr_engine == TesseractEngine.name:
            hint = "install it with: winget install UB-Mannheim.TesseractOCR"
        else:
            hint = f"install it with: pip install {config.ocr_engine}"
        raise RuntimeError(f"OCR engine {config.ocr_engine!r} not found - {hint}")
    return engine


def retry_ocr(store, config, item_id: int) -> str:
    """Re-run OCR for one stored image item (UI action). Returns the text.

    Raises a helpful error if the item is missing, is not an image, its file
    is gone, or the engine fails.
    """
    item = store.get(item_id)
    if item is None:
        raise ValueError(f"item {item_id} no longer exists")
    if item.kind != "image" or not item.image_path:
        raise ValueError("OCR retry only applies to image items")
    if not Path(item.image_path).is_file():
        store.mark_ocr_failed(item_id)
        raise RuntimeError("the image file is missing from disk")
    engine = create_engine(config)
    try:
        text = engine.extract_text(item.image_path)
    except Exception:
        store.mark_ocr_failed(item_id)
        raise
    if text.strip():
        store.set_ocr_text(item_id, text)
    else:
        store.set_ocr_status(item_id, None)
    return text

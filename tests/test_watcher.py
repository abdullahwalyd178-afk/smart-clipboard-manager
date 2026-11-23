"""Watcher behavior with a fake clipboard and a fake OCR engine."""

import io

import pytest

from PIL import Image

from clipboard_manager.watcher import ClipboardProvider, ClipboardWatcher


def make_png(color=(200, 30, 30)) -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", (40, 40), color).save(buf, format="PNG")
    return buf.getvalue()


PNG_A = make_png((200, 30, 30))
PNG_B = make_png((30, 200, 30))


class FakeProvider(ClipboardProvider):
    """Scriptable clipboard modeling the real thing: one content at a time.
    Setting text clears the image and vice versa, like a real clipboard."""

    def __init__(self):
        self._text = None
        self._image = None
        self.set_calls = []

    @property
    def text(self):
        return self._text

    @text.setter
    def text(self, value):
        self._text = value
        if value is not None:
            self._image = None

    @property
    def image(self):
        return self._image

    @image.setter
    def image(self, value):
        self._image = value
        if value is not None:
            self._text = None

    def get_text(self):
        return self._text

    def get_image_png_bytes(self):
        return self._image

    def set_text(self, text):
        self.set_calls.append(text)
        self.text = text  # real clipboards change when written


class FakeOCR:
    name = "fake"

    def __init__(self, result="OCR RESULT"):
        self.result = result
        self.calls = []

    def extract_text(self, path):
        self.calls.append(path)
        return self.result


def make_watcher(store, images_dir, provider, ocr=None, auto_copy=True):
    return ClipboardWatcher(
        store,
        provider,
        images_dir,
        ocr_engine=ocr,
        copy_ocr_result_to_clipboard=auto_copy,
    )


def test_captures_new_text(store, images_dir):
    provider = FakeProvider()
    provider.text = "first clip"
    watcher = make_watcher(store, images_dir, provider)

    item = watcher.poll_once()
    assert item is not None and item.text == "first clip"
    assert store.count() == 1


def test_same_clip_not_captured_twice(store, images_dir):
    provider = FakeProvider()
    provider.text = "static clipboard"
    watcher = make_watcher(store, images_dir, provider)

    assert watcher.poll_once() is not None
    assert watcher.poll_once() is None  # unchanged clipboard
    assert store.count() == 1


def test_paused_watcher_captures_nothing(store, images_dir):
    provider = FakeProvider()
    provider.text = "secret while paused"
    watcher = make_watcher(store, images_dir, provider)
    watcher.pause()

    assert watcher.poll_once() is None
    assert store.count() == 0

    watcher.resume()
    assert watcher.poll_once() is not None
    assert store.count() == 1


def test_image_is_stored_and_ocrd(store, images_dir):
    provider = FakeProvider()
    provider.image = PNG_A
    ocr = FakeOCR("extracted: 2+2=4")
    watcher = make_watcher(store, images_dir, provider, ocr=ocr)

    item = watcher.poll_once()
    assert item is not None and item.kind == "image"
    assert item.image_path and (images_dir / item.image_path.split("/")[-1]).exists()
    assert ocr.calls == [item.image_path]
    assert store.get(item.id).ocr_text == "extracted: 2+2=4"


def test_ocr_result_copied_to_clipboard_and_not_recaptured(store, images_dir):
    provider = FakeProvider()
    provider.image = PNG_A
    ocr = FakeOCR("READY TO PASTE")
    watcher = make_watcher(store, images_dir, provider, ocr=ocr)

    watcher.poll_once()
    assert provider.set_calls == ["READY TO PASTE"]
    assert provider.text == "READY TO PASTE"

    # The OCR text we placed ourselves must not become a new history item.
    assert watcher.poll_once() is None
    assert store.count() == 1


def test_ocr_never_overwrites_newer_user_copy(store, images_dir):
    """If the user copied something new while OCR ran, keep their clip."""

    class SlowUserCopyOCR(FakeOCR):
        def extract_text(self, path):
            provider.text = "user copied this meanwhile"  # user acts during OCR
            provider.image = None
            return super().extract_text(path)

    provider = FakeProvider()
    provider.image = PNG_A
    ocr = SlowUserCopyOCR("stale OCR text")
    watcher = make_watcher(store, images_dir, provider, ocr=ocr)

    watcher.poll_once()
    assert provider.set_calls == []  # OCR result was NOT placed
    assert provider.text == "user copied this meanwhile"


def test_different_images_both_captured(store, images_dir):
    provider = FakeProvider()
    watcher = make_watcher(store, images_dir, provider, ocr=FakeOCR())

    provider.image = PNG_A
    watcher.poll_once()
    provider.image = PNG_B
    watcher.poll_once()
    assert store.count() == 2


def test_auto_copy_disabled(store, images_dir):
    provider = FakeProvider()
    provider.image = PNG_A
    watcher = make_watcher(store, images_dir, provider, ocr=FakeOCR(), auto_copy=False)

    watcher.poll_once()
    assert provider.set_calls == []


def test_ocr_failure_does_not_break_capture(store, images_dir):
    class BrokenOCR(FakeOCR):
        def extract_text(self, path):
            raise RuntimeError("engine exploded")

    provider = FakeProvider()
    provider.image = PNG_A
    watcher = make_watcher(store, images_dir, provider, ocr=BrokenOCR())

    item = watcher.poll_once()
    assert item is not None
    assert store.get(item.id).ocr_text is None
    # next image still works after the failure
    provider.image = PNG_B
    assert watcher.poll_once() is not None
    assert store.count() == 2


def test_failed_image_insert_preserves_path_referenced_by_another_row(
    store, images_dir, monkeypatch
):
    from clipboard_manager.models import IMAGE, ClipboardItem

    provider = FakeProvider()
    provider.image = PNG_A
    watcher = make_watcher(store, images_dir, provider)
    digest = ClipboardItem.hash_bytes(PNG_A)
    image_path = images_dir / f"{digest[:16]}.png"

    referenced = ClipboardItem(
        id=None,
        kind=IMAGE,
        content_hash="other-hash",
        image_path=str(image_path),
        created_at=ClipboardItem.utcnow_iso(),
    )
    referenced.id = store._insert(referenced)

    def fail_insert(*_args, **_kwargs):
        raise RuntimeError("simulated database write failure")

    monkeypatch.setattr(store, "add_image", fail_insert)
    with pytest.raises(RuntimeError, match="simulated database write failure"):
        watcher.poll_once()

    assert store.image_path_referenced(str(image_path))
    assert image_path.exists()


def test_max_items_is_enforced_after_each_new_clip(store, images_dir):
    provider = FakeProvider()
    watcher = ClipboardWatcher(store, provider, images_dir, max_items=1)

    provider.text = "first"
    assert watcher.poll_once() is not None
    provider.text = "second"
    assert watcher.poll_once() is not None

    items = store.list_items()
    assert len(items) == 1
    assert items[0].text == "second"

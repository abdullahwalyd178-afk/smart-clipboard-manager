"""Watcher behavior with a fake clipboard and a fake OCR engine."""

import io
import threading
import time
from pathlib import Path

from PIL import Image

from clipboard_manager.watcher import OCR_QUEUE_MAXSIZE, ClipboardProvider, ClipboardWatcher


def make_png(color=(200, 30, 30)) -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", (40, 40), color).save(buf, format="PNG")
    return buf.getvalue()


PNG_A = make_png((200, 30, 30))
PNG_B = make_png((30, 200, 30))


def wait_until(predicate, timeout=2):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(0.01)
    return bool(predicate())


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
        self.finished = threading.Event()

    def extract_text(self, path):
        self.calls.append(path)
        self.finished.set()
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
    assert item.image_path and Path(item.image_path).exists()
    assert ocr.finished.wait(timeout=2)
    assert wait_until(lambda: store.get(item.id).ocr_text == "extracted: 2+2=4")
    assert ocr.calls == [item.image_path]


def test_ocr_result_copied_to_clipboard_and_not_recaptured(store, images_dir):
    provider = FakeProvider()
    provider.image = PNG_A
    ocr = FakeOCR("READY TO PASTE")
    watcher = make_watcher(store, images_dir, provider, ocr=ocr)

    item = watcher.poll_once()
    assert item is not None
    assert ocr.finished.wait(timeout=2)
    assert wait_until(lambda: provider.set_calls == ["READY TO PASTE"])
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
    assert ocr.finished.wait(timeout=2)
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
    ocr = FakeOCR()
    watcher = make_watcher(store, images_dir, provider, ocr=ocr, auto_copy=False)

    watcher.poll_once()
    assert ocr.finished.wait(timeout=2)
    assert provider.set_calls == []


def test_ocr_failure_does_not_break_capture(store, images_dir):
    class BrokenOCR(FakeOCR):
        def extract_text(self, path):
            self.finished.set()
            raise RuntimeError("engine exploded")

    provider = FakeProvider()
    provider.image = PNG_A
    ocr = BrokenOCR()
    watcher = make_watcher(store, images_dir, provider, ocr=ocr)

    item = watcher.poll_once()
    assert item is not None
    assert ocr.finished.wait(timeout=2)
    assert store.get(item.id).ocr_text is None
    # next image still works after the failure
    provider.image = PNG_B
    assert watcher.poll_once() is not None
    assert store.count() == 2



def test_max_items_is_enforced_during_capture_and_old_image_is_removed(store, images_dir):
    provider = FakeProvider()
    watcher = ClipboardWatcher(
        store, provider, images_dir, max_items=1
    )

    provider.image = PNG_A
    first = watcher.poll_once()
    assert first is not None and first.kind == "image"
    saved_image = Path(first.image_path)
    assert saved_image.exists()

    provider.text = "newer text clip"
    second = watcher.poll_once()
    assert second is not None and second.text == "newer text clip"
    assert store.count() == 1
    assert store.get(first.id) is None
    assert not saved_image.exists()


def test_zero_max_items_means_unlimited(store, images_dir):
    provider = FakeProvider()
    watcher = ClipboardWatcher(store, provider, images_dir, max_items=0)
    for value in ("one", "two", "three"):
        provider.text = value
        watcher.poll_once()
    assert store.count() == 3


def test_invalid_watcher_limits_are_rejected(store, images_dir):
    import pytest

    provider = FakeProvider()
    with pytest.raises(ValueError, match="poll_interval"):
        ClipboardWatcher(store, provider, images_dir, poll_interval=0)
    with pytest.raises(ValueError, match="max_items"):
        ClipboardWatcher(store, provider, images_dir, max_items=-1)


def test_stop_reports_busy_watcher_and_can_be_retried(store, images_dir):
    import threading

    entered = threading.Event()
    release = threading.Event()

    class BlockingProvider(FakeProvider):
        def get_text(self):
            entered.set()
            release.wait(timeout=2)
            return None

    watcher = ClipboardWatcher(store, BlockingProvider(), images_dir, poll_interval=0.01)
    watcher.start()
    assert entered.wait(timeout=1)
    assert watcher.stop(timeout=0.01) is False
    release.set()
    assert watcher.stop(timeout=1) is True


def test_slow_ocr_does_not_block_clipboard_polling(store, images_dir):
    class BlockingOCR(FakeOCR):
        def __init__(self):
            super().__init__("background OCR")
            self.entered = threading.Event()
            self.release = threading.Event()

        def extract_text(self, path):
            self.calls.append(path)
            self.entered.set()
            self.release.wait(timeout=2)
            self.finished.set()
            return self.result

    provider = FakeProvider()
    provider.image = PNG_A
    ocr = BlockingOCR()
    watcher = make_watcher(store, images_dir, provider, ocr=ocr)

    image_item = watcher.poll_once()
    assert image_item is not None
    assert ocr.entered.wait(timeout=1)

    # OCR is deliberately blocked, but a later clipboard change is still
    # captured synchronously by the independent polling path.
    provider.text = "copied while OCR is busy"
    text_item = watcher.poll_once()
    assert text_item is not None and text_item.text == "copied while OCR is busy"
    assert store.count() == 2

    ocr.release.set()
    assert ocr.finished.wait(timeout=2)
    assert wait_until(lambda: store.get(image_item.id).ocr_text == "background OCR")
    assert watcher.stop(timeout=2) is True


def test_stop_waits_for_queued_ocr_before_database_can_close(store, images_dir):
    class BlockingOCR(FakeOCR):
        def __init__(self):
            super().__init__("finished OCR")
            self.entered = threading.Event()
            self.release = threading.Event()

        def extract_text(self, path):
            self.entered.set()
            self.release.wait(timeout=2)
            self.finished.set()
            return self.result

    provider = FakeProvider()
    provider.image = PNG_A
    ocr = BlockingOCR()
    watcher = make_watcher(store, images_dir, provider, ocr=ocr)

    item = watcher.poll_once()
    assert item is not None
    assert ocr.entered.wait(timeout=1)

    # The caller must keep SQLite open while OCR is still using it.
    assert watcher.stop(timeout=0.01) is False
    ocr.release.set()
    assert watcher.stop(timeout=2) is True
    assert store.get(item.id).ocr_text == "finished OCR"



def test_failed_persistence_does_not_mark_clip_as_seen(store, images_dir, monkeypatch):
    provider = FakeProvider()
    watcher = make_watcher(store, images_dir, provider)

    original_add_text = store.add_text

    def fail_once(*args, **kwargs):
        raise RuntimeError("temporary database failure")

    provider.text = "retry this clip"
    monkeypatch.setattr(store, "add_text", fail_once)
    import pytest
    with pytest.raises(RuntimeError, match="temporary database failure"):
        watcher.poll_once()
    assert watcher._last_hash is None

    monkeypatch.setattr(store, "add_text", original_add_text)
    item = watcher.poll_once()
    assert item is not None and item.text == "retry this clip"
    assert store.count() == 1

    # The same guarantee applies to image persistence.
    provider.image = PNG_A
    original_add_image = store.add_image
    monkeypatch.setattr(store, "add_image", fail_once)
    with pytest.raises(RuntimeError, match="temporary database failure"):
        watcher.poll_once()
    assert watcher._last_hash == item.content_hash

    monkeypatch.setattr(store, "add_image", original_add_image)
    image_item = watcher.poll_once()
    assert image_item is not None and image_item.kind == "image"
    assert store.count() == 2


def test_restart_after_timed_out_ocr_stop_processes_tasks_queued_after_sentinel(store, images_dir):
    class FirstCallBlockingOCR(FakeOCR):
        def __init__(self):
            super().__init__("processed")
            self.entered = threading.Event()
            self.release = threading.Event()
            self.call_count = 0

        def extract_text(self, path):
            self.call_count += 1
            if self.call_count == 1:
                self.entered.set()
                self.release.wait(timeout=3)
            return f"processed {self.call_count}"

    provider = FakeProvider()
    ocr = FirstCallBlockingOCR()
    watcher = make_watcher(store, images_dir, provider, ocr=ocr)

    provider.image = PNG_A
    first = watcher.poll_once()
    assert first is not None
    assert ocr.entered.wait(timeout=1)

    # stop queues its sentinel behind the currently-running OCR task.
    assert watcher.stop(timeout=0.01) is False

    # Restart while the old worker is still busy, then queue a new image
    # behind the sentinel. The old worker must hand off to a fresh worker.
    watcher.start()
    # Let the watcher perform its immediate first poll of the unchanged clip;
    # the long interval keeps the test's explicit poll deterministic.
    time.sleep(0.05)
    provider.image = PNG_B
    second = watcher.poll_once()
    assert second is not None and second.id != first.id

    ocr.release.set()
    assert wait_until(lambda: ocr.call_count == 2, timeout=2)
    assert wait_until(
        lambda: store.get(second.id).ocr_text == "processed 2", timeout=2
    )
    assert watcher.stop(timeout=2) is True


def test_ocr_queue_is_bounded_without_dropping_captured_images(store, images_dir):
    class BlockingOCR(FakeOCR):
        def __init__(self):
            super().__init__("done")
            self.entered = threading.Event()
            self.release = threading.Event()

        def extract_text(self, path):
            self.entered.set()
            self.release.wait(timeout=3)
            return self.result

    provider = FakeProvider()
    ocr = BlockingOCR()
    watcher = make_watcher(store, images_dir, provider, ocr=ocr)

    provider.image = PNG_A
    first = watcher.poll_once()
    assert first is not None
    assert ocr.entered.wait(timeout=1)

    assert watcher._ocr_queue.maxsize == OCR_QUEUE_MAXSIZE
    # Hold the worker on its first image and fill every pending OCR slot.
    for index in range(OCR_QUEUE_MAXSIZE):
        watcher._ocr_queue.put_nowait((10_000 + index, "unused.png", "unused"))

    provider.image = PNG_B
    second = watcher.poll_once()
    assert second is not None and second.kind == "image"
    assert store.get(second.id) is not None
    assert store.count() == 2
    assert watcher._ocr_queue.qsize() == OCR_QUEUE_MAXSIZE

    # A full queue must not make shutdown block forever.
    assert watcher.stop(timeout=0.01) is False
    ocr.release.set()
    assert watcher.stop(timeout=3) is True


def test_failed_image_insert_cleans_only_the_newly_created_file(store, images_dir, monkeypatch):
    from clipboard_manager.models import ClipboardItem

    provider = FakeProvider()
    watcher = make_watcher(store, images_dir, provider)
    digest = ClipboardItem.hash_bytes(PNG_A)
    image_path = Path(images_dir) / f"{digest[:16]}.png"

    def fail_insert(*args, **kwargs):
        raise RuntimeError("database write failed")

    provider.image = PNG_A
    monkeypatch.setattr(store, "add_image", fail_insert)
    import pytest
    with pytest.raises(RuntimeError, match="database write failed"):
        watcher.poll_once()
    assert not image_path.exists()
    assert watcher._last_hash is None

    # A file that predates this failed attempt may be shared/referenced;
    # cleanup must never delete it.
    image_path.parent.mkdir(parents=True, exist_ok=True)
    image_path.write_bytes(b"pre-existing image")
    with pytest.raises(RuntimeError, match="database write failed"):
        watcher.poll_once()
    assert image_path.read_bytes() == b"pre-existing image"


def test_stop_does_not_report_success_if_restart_replaces_worker_during_join(store, images_dir):
    class BlockingOCR(FakeOCR):
        def __init__(self):
            super().__init__("done")
            self.entered = threading.Event()
            self.release = threading.Event()
            self.calls = 0

        def extract_text(self, path):
            self.calls += 1
            if self.calls == 1:
                self.entered.set()
                self.release.wait(timeout=3)
            return f"result {self.calls}"

    provider = FakeProvider()
    ocr = BlockingOCR()
    watcher = make_watcher(store, images_dir, provider, ocr=ocr)
    provider.image = PNG_A
    first = watcher.poll_once()
    assert first is not None and ocr.entered.wait(timeout=1)

    stop_result = []
    stopper = threading.Thread(target=lambda: stop_result.append(watcher.stop(timeout=2)))
    stopper.start()
    assert wait_until(lambda: watcher._ocr_shutdown_requested, timeout=1)

    watcher.start()
    time.sleep(0.05)
    provider.image = PNG_B
    second = watcher.poll_once()
    assert second is not None and second.id != first.id

    ocr.release.set()
    stopper.join(timeout=2)
    assert not stopper.is_alive()
    assert stop_result == [False]
    assert wait_until(lambda: store.get(second.id).ocr_text == "result 2", timeout=2)
    assert watcher.stop(timeout=2) is True


def test_empty_ocr_result_is_persisted_as_completed(store, images_dir):
    provider = FakeProvider()
    ocr = FakeOCR("")
    watcher = make_watcher(store, images_dir, provider)

    # Attach the engine after construction to keep the test focused on the
    # worker's result handling rather than worker startup behavior.
    watcher.ocr_engine = ocr
    provider.image = PNG_A
    item = watcher.poll_once()
    assert item is not None

    watcher._process_ocr(item.id, item.image_path, item.content_hash)

    saved = store.get(item.id)
    assert saved is not None
    assert saved.ocr_text == ""
    assert provider.set_calls == []

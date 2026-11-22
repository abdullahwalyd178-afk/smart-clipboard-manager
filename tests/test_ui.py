"""History window: real Tkinter widgets, driven without a display where absent.

These tests construct the actual window and exercise search, filters and
actions against a real store. They need a display; under CI or headless Linux
without one they skip (run locally under Xvfb or on Windows).
"""

import os

import pytest

tk = pytest.importorskip("tkinter", reason="tkinter not installed")

from clipboard_manager.config import Config  # noqa: E402
from clipboard_manager.storage import ClipboardStore  # noqa: E402
from clipboard_manager.ui import HistoryWindow, _display_text  # noqa: E402
from clipboard_manager.watcher import ClipboardProvider  # noqa: E402


class FakeProvider(ClipboardProvider):
    def __init__(self):
        self.set_calls = []

    def get_text(self):
        return None

    def get_image_png_bytes(self):
        return None

    def set_text(self, text):
        self.set_calls.append(text)


@pytest.fixture
def window(tmp_path):
    if not os.environ.get("DISPLAY") and os.name != "nt":
        pytest.skip("no display available")
    store = ClipboardStore(tmp_path / "history.db")
    cfg = Config(data_dir=str(tmp_path))
    win = HistoryWindow(store, FakeProvider(), cfg)
    yield win
    win.close()


def _rows(win):
    return win.tree.get_children()


def test_window_lists_and_searches(window):
    window.store.add_text("buy milk")
    window.store.add_text("call mom")
    window.refresh()
    assert len(_rows(window)) == 2

    window.search_var.set("milk")
    window.refresh()
    assert len(_rows(window)) == 1
    assert "milk" in window.tree.item(_rows(window)[0])["values"][2]


def test_favorites_filter(window):
    a, _ = window.store.add_text("starred")
    window.store.add_text("plain")
    window.store.set_favorite(a.id, True)

    window.filter_var.set("Favorites")
    window.refresh()
    assert len(_rows(window)) == 1


def test_copy_back_uses_provider(window):
    item, _ = window.store.add_text("copy me back")
    window.refresh()
    window.tree.selection_set(str(item.id))
    window.copy_back()
    assert window.provider.set_calls == ["copy me back"]


def test_pin_and_favorite_buttons(window):
    item, _ = window.store.add_text("toggle me")
    window.refresh()
    window.tree.selection_set(str(item.id))
    window.toggle_pin()
    window.toggle_favorite()
    updated = window.store.get(item.id)
    assert updated.pinned and updated.favorite


def test_delete_removes_row_and_image(window, tmp_path):
    image = tmp_path / "img.png"
    image.write_bytes(b"png")
    item, _ = window.store.add_image(str(image), digest="9" * 64)
    window.refresh()
    window.tree.selection_set(str(item.id))
    window.delete()
    assert window.store.count() == 0
    assert not image.exists()


class TestDisplayText:
    def test_plain_text_passthrough(self):
        assert _display_text("hello world") == "hello world"

    def test_arabic_is_reshaped_for_tk(self):
        pytest.importorskip("arabic_reshaper")
        shaped = _display_text("نص عربي")
        assert shaped != "نص عربي"  # pre-shaped + bidi-reordered for Tk
        assert any("ﭐ" <= ch <= "﷿" or "ﹰ" <= ch <= "﻿" for ch in shaped)

    def test_arabic_missing_libs_falls_back(self, monkeypatch):
        import builtins

        real_import = builtins.__import__

        def fake_import(name, *args, **kwargs):
            if name in ("arabic_reshaper", "bidi.algorithm"):
                raise ImportError(name)
            return real_import(name, *args, **kwargs)

        monkeypatch.setattr(builtins, "__import__", fake_import)
        assert _display_text("نص عربي") == "نص عربي"

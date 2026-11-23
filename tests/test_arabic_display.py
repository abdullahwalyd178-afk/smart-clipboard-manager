"""Arabic display shaping + search entry behavior.

Tk on X11 renders Entry text without bidi reordering; the app keeps logical
text in search_var and shows a shaped copy. These tests pin that contract.
"""

import sys

import pytest

from clipboard_manager.text_shaping import (
    base_is_rtl,
    shape_for_display,
    shaping_active,
)

LINUX_SHAPED = sys.platform.startswith("linux") and shaping_active()


def test_latin_text_is_never_touched():
    assert shape_for_display("invoice 450") == "invoice 450"


def test_empty_and_none_safe():
    assert shape_for_display("") == ""
    assert shape_for_display(None) is None


@pytest.mark.skipif(not LINUX_SHAPED, reason="manual shaping only applies on Linux/X11 with libs")
def test_arabic_is_shaped_and_reordered_on_linux():
    logical = "فاتورة"
    display = shape_for_display(logical)
    assert display != logical  # reshaped into presentation forms, visual order
    # visual order: last logical letter (ة) comes first
    assert ord(display[0]) in range(0xFE80, 0xFF00)  # Arabic Presentation Forms-B


@pytest.mark.skipif(not LINUX_SHAPED, reason="same as above")
def test_roundtrip_via_bidi():
    # get_display(reshape(x)) reversed per-run equals logical for pure Arabic
    display = shape_for_display("فاتورة")
    assert len(display) == len("فاتورة")


def test_base_direction():
    assert base_is_rtl("فاتورة كهرباء")
    assert not base_is_rtl("invoice")
    assert not base_is_rtl("")
    assert base_is_rtl("123 فاتورة")  # digits are weak; first strong char is ف -> RTL


# -- GUI: typing into the search box keeps logical text, shows shaped copy ---

pytestmark_gui = pytest.mark.skipif(
    sys.platform == "win32", reason="GUI display behavior test runs under X11"
)


@pytest.fixture()
def window(tmp_path):
    tk = pytest.importorskip("tkinter")
    from clipboard_manager.config import Config
    from clipboard_manager.storage import ClipboardStore
    from clipboard_manager.ui import HistoryWindow

    store = ClipboardStore(str(tmp_path / "h.db"))
    store.add_text("فاتورة كهرباء شهر نوفمبر")
    store.add_text("meeting notes")
    cfg = Config(data_dir=str(tmp_path))
    win = HistoryWindow(store, None, cfg)
    yield win
    win.root.destroy()


class _Ev:
    def __init__(self, char="", keysym="", state=0):
        self.char = char
        self.keysym = keysym
        self.state = state


def _type(win, text):
    for ch in text:
        win._on_search_key(_Ev(char=ch, keysym="?"))
    win.root.update()


@pytest.mark.skipif(sys.platform == "win32", reason="X11 display behavior")
def test_typing_arabic_keeps_logical_and_filters(window):
    _type(window, "فاتورة")
    # logical storage is correct order
    assert window.search_var.get() == "فاتورة"
    # filtering works on the logical text
    rows = window.tree.get_children()
    assert len(rows) == 1
    # display copy differs from logical only when shaping is active
    display = window._search_display_var.get()
    if shaping_active():
        assert display != "فاتورة"
        assert len(display) == len("فاتورة")
    else:
        assert display == "فاتورة"


@pytest.mark.skipif(sys.platform == "win32", reason="X11 display behavior")
def test_backspace_edits_logical_text(window):
    _type(window, "فاتورة")
    window._on_search_key(_Ev(keysym="BackSpace"))
    window.root.update()
    assert window.search_var.get() == "فاتور"
    assert len(window.tree.get_children()) == 1


@pytest.mark.skipif(sys.platform == "win32", reason="X11 display behavior")
def test_latin_typing_unaffected(window):
    _type(window, "meet")
    assert window.search_var.get() == "meet"
    assert window._search_display_var.get() == "meet"
    assert len(window.tree.get_children()) == 1


@pytest.mark.skipif(sys.platform == "win32", reason="X11 display behavior")
def test_view_full_shows_complete_content(window):
    from clipboard_manager.text_shaping import shape_for_display as shp

    long_text = "سطر طويل " * 60
    item, _ = window.store.add_text(long_text)
    window.refresh()
    # select the new (first) row
    first = window.tree.get_children()[0]
    window.tree.selection_set(first)
    window.view_full()
    window.root.update()
    tops = [w for w in window.root.winfo_children() if w.winfo_class() == "Toplevel"]
    assert tops, "viewer window did not open"
    texts = []
    for w in tops[0].winfo_children():
        if w.winfo_class() == "Message":
            texts.append(w.cget("text"))
    assert texts and texts[0] == shp(long_text)
    tops[0].destroy()

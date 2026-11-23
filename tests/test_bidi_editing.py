"""Bidi search-entry editing and logical-copy tests.

Two layers:
- Editing/copy LOGIC tests are platform-independent: with no shaping the
  display->logical map is the identity, so caret/selection/Delete/copy must
  still behave. These run on the Windows CI job (real bundled Tk).
- Mapping/shaping tests need the Linux manual-shaping path (arabic-reshaper +
  python-bidi) and are skipped where it is inactive.
"""

import pytest

from clipboard_manager.text_shaping import (
    logical_slice,
    shape_with_map,
    shaping_active,
)

SHAPED = shaping_active()

# ---------------------------------------------------------------------------
# pure mapping tests (no GUI); need the shaping libs
# ---------------------------------------------------------------------------

requires_shaping = pytest.mark.skipif(
    not SHAPED, reason="manual shaping inactive (needs Linux + arabic-reshaper/python-bidi)"
)


@requires_shaping
def test_map_is_true_permutation_ligature_context():
    # lam-alef pairs must NOT collapse into one glyph: ligatures are disabled
    for text in ("سلام عليكم", "لا إله إلا الله", "فاتورة"):
        _, d2l = shape_with_map(text)
        assert sorted(d2l) == list(range(len(text)))


@requires_shaping
def test_map_permutation_diacritics_and_combining_marks():
    # harakat are combining marks; they must be preserved 1:1, not dropped
    for text in ("مُحَمَّد", "بِسْمِ اللَّهِ الرَّحْمَٰنِ"):
        display, d2l = shape_with_map(text)
        assert sorted(d2l) == list(range(len(text)))
        assert len(display) == len(text)
        # full-range copy reconstructs the original text exactly
        assert logical_slice(text, d2l, 0, len(d2l)) == text


@requires_shaping
def test_map_mixed_rtl_digits():
    text = "فاتورة 450 جنيه"
    display, d2l = shape_with_map(text)
    assert sorted(d2l) == list(range(len(text)))
    assert "450" in display  # digits keep logical order inside RTL text
    assert logical_slice(text, d2l, 0, len(d2l)) == text


@requires_shaping
def test_bidi_control_characters_have_defined_handling():
    # RLM is kept in the display by the algorithm -> full permutation
    text = "abc‏فاتورة"
    _, d2l = shape_with_map(text)
    assert sorted(d2l) == list(range(len(text)))
    # Latin-only text takes the identity path even with explicit override
    # controls: shaping is only for RTL content, so controls stay and the
    # logical text is preserved byte-for-byte on copy
    ctrl = "a‮bc‬"
    display, d2l = shape_with_map(ctrl)
    assert d2l == [0, 1, 2, 3, 4]
    assert logical_slice(ctrl, d2l, 0, len(d2l)) == ctrl
    # RTL text with explicit controls: the algorithm consumes the control
    # codepoints, so they are absent from the map but never dropped from the
    # stored logical text
    rtl_ctrl = "x‮فاتورة‬"
    _, d2l2 = shape_with_map(rtl_ctrl)
    assert 1 not in d2l2 and 8 not in d2l2
    assert logical_slice(rtl_ctrl, d2l2, 0, len(d2l2)) == "xفاتورة"


@requires_shaping
def test_logical_slice_partial_selection():
    text = "abcفاتورة"
    _, d2l = shape_with_map(text)
    assert logical_slice(text, d2l, 0, 3) == "abc"
    assert logical_slice(text, d2l, 3, len(d2l)) == "فاتورة"


@requires_shaping
def test_logical_slice_disjoint_selection_returns_only_selected():
    # Visually contiguous selection across the direction boundary maps to
    # DISJOINT logical ranges; copy must return only the selected characters
    # in logical order, never the bounding interval.
    text = "abcفاتورة"
    _, d2l = shape_with_map(text)
    # display positions 1..4 -> logical {1, 2, 7, 8}: "bc" + "رة"
    assert logical_slice(text, d2l, 1, 5) == "bcرة"
    # the bounding interval would wrongly include unselected فاتو
    assert logical_slice(text, d2l, 1, 5) != text[1:9]


# ---------------------------------------------------------------------------
# GUI: entry editing and copy behavior (platform-independent; run on CI)
# ---------------------------------------------------------------------------


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


def test_delete_key_removes_only_char_at_caret(window):
    _type(window, "invoice")
    window._search_entry.icursor(0)
    window._on_search_key(_Ev(keysym="Delete"))
    assert window.search_var.get() == "nvoice"
    window._search_entry.icursor(2)
    window._on_search_key(_Ev(keysym="Delete"))
    assert window.search_var.get() == "nvice"


def test_backspace_removes_char_before_caret(window):
    _type(window, "invoice")
    window._search_entry.icursor(3)
    window._on_search_key(_Ev(keysym="BackSpace"))
    assert window.search_var.get() == "inoice"


def test_delete_at_end_does_not_clear_field(window):
    # regression: Delete used to wipe the whole search text
    _type(window, "invoice")
    window._search_entry.icursor(7)
    window._on_search_key(_Ev(keysym="Delete"))
    assert window.search_var.get() == "invoice"


def test_selection_delete_removes_only_selection(window):
    _type(window, "invoice")
    window._search_entry.select_range(1, 4)
    window._on_search_key(_Ev(keysym="Delete"))
    assert window.search_var.get() == "iice"


def test_insert_at_caret_mid_text(window):
    _type(window, "ac")
    window._search_entry.icursor(1)
    window._on_search_key(_Ev(char="b", keysym="?"))
    assert window.search_var.get() == "abc"


def test_typed_char_replaces_selection(window):
    _type(window, "invoice")
    window._search_entry.select_range(0, 3)
    window._on_search_key(_Ev(char="X", keysym="?"))
    assert window.search_var.get() == "Xoice"


def test_copy_selection_puts_logical_text_on_clipboard(window):
    _type(window, "invoice")
    window._search_entry.select_range(0, 3)
    window._on_search_copy(_Ev())
    assert window.root.clipboard_get() == "inv"


def test_paste_inserts_at_caret(window):
    _type(window, "ac")
    window._search_entry.icursor(1)
    window.root.clipboard_clear()
    window.root.clipboard_append("XYZ")
    window._on_search_paste(_Ev())
    assert window.search_var.get() == "aXYZc"


@requires_shaping
def test_copy_arabic_selection_returns_original_codepoints(window):
    _type(window, "فاتورة")
    window._search_entry.select_range(0, "end")
    window._on_search_copy(_Ev())
    # original logical Unicode, not presentation-form display codepoints
    assert window.root.clipboard_get() == "فاتورة"


@requires_shaping
def test_copy_mixed_disjoint_selection_returns_only_selected_logical(window):
    _type(window, "abcفاتورة")
    window._search_entry.select_range(1, 5)
    window._on_search_copy(_Ev())
    assert window.root.clipboard_get() == "bcرة"


@requires_shaping
def test_backspace_rtl_mid_text_removes_char_before_visual_caret(window):
    _type(window, "فاتورة")
    # caret after the 3rd displayed char; display is reversed, so that is
    # logical index 3 (و)
    window._search_entry.icursor(3)
    window._on_search_key(_Ev(keysym="BackSpace"))
    assert window.search_var.get() == "فاترة"


@requires_shaping
def test_delete_rtl_visual_selection(window):
    _type(window, "abcفاتورة")
    # display positions 3..4 are the last two logical chars (ر, ة)
    window._search_entry.select_range(3, 5)
    window._on_search_key(_Ev(keysym="Delete"))
    assert window.search_var.get() == "abcفاتو"


@requires_shaping
def test_insert_at_visual_start_of_rtl_appends_logically(window):
    _type(window, "فاتورة")
    window._search_entry.icursor(0)
    window._on_search_key(_Ev(char="x", keysym="?"))
    assert window.search_var.get() == "فاتورةx"


@requires_shaping
def test_viewer_copy_returns_logical_text(window):
    import tkinter as tk  # noqa: F401

    body = "فاتورة كهرباء\ninvoice 450"
    window.store.add_text(body)
    window.refresh()
    first = window.tree.get_children()[0]
    window.tree.selection_set(first)
    window.view_full()
    window.root.update()
    tops = [w for w in window.root.winfo_children() if w.winfo_class() == "Toplevel"]
    assert tops

    def find_text(w):
        if w.winfo_class() == "Text":
            return w
        for c in w.winfo_children():
            found = find_text(c)
            if found is not None:
                return found
        return None

    widget = find_text(tops[0])
    assert widget is not None
    # first 6 display chars of line 1 = last word of the RTL line, logically
    widget.tag_add("sel", "1.0", "1.6")
    window._viewer_copy(widget, body.split("\n"))
    assert window.root.clipboard_get() == "كهرباء"
    # whole-content copy returns the original body exactly
    widget.tag_add("sel", "1.0", "2.end")
    window._viewer_copy(widget, body.split("\n"))
    assert window.root.clipboard_get() == body
    tops[0].destroy()


def test_shaping_active_on_linux_when_libs_installed():
    """Guard regression: if the libs import, the shaping path MUST be active
    (a silent identity fallback once shipped unshaped Arabic as 'done')."""
    import importlib.util
    import sys as _sys

    if not _sys.platform.startswith("linux"):
        pytest.skip("linux-only assertion")
    if importlib.util.find_spec("arabic_reshaper") is None or importlib.util.find_spec("bidi") is None:
        pytest.skip("shaping libs not installed")
    from clipboard_manager import text_shaping as _ts

    assert _ts.shaping_active() is True


def test_shaping_inactive_on_windows():
    """Windows/macOS rely on the OS text stack; manual shaping must stay off."""
    import sys as _sys

    if not _sys.platform.startswith(("win", "darwin")):
        pytest.skip("windows/macos-only assertion")
    from clipboard_manager import text_shaping as _ts

    assert _ts.shaping_active() is False

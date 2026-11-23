"""Rich Edit 4.1 viewer tests (Windows-only; skipped elsewhere).

These exercise the real native control: logical text round-trip, logical
selection offsets, native clipboard copy, resize and lifecycle. Pixel-level
RTL layout evidence comes from the CI viewer probe captures.
"""

import sys

import pytest

pytestmark = pytest.mark.skipif(sys.platform != "win32", reason="win32-only native control")

LONG_AR = "هذا سطر عربي طويل مخصص لاختبار التفاف الأسطر داخل عارض المحتوى عند عرض ضيق، ويجب أن يبقى اتجاه الفقرة من اليمين إلى اليسار مع اتصال الحروف وظهورها بشكل سليم تمامًا."
PAREN = "(تقرير 2026) رقم 12.5 في «القائمة» ثم [نهائي] و(ملاحظة 7)"
AN_DIGITS = "كلمة ١٢٣ كلمة ثانية ٤٥٦ كلمة ثالثة"
DIACRITICS = "بِسْمِ اللَّهِ الرَّحْمَٰنِ الرَّحِيمِ"
MIXED = "السطر 01: تقرير مراجعة المشروع - budget line 01 with أرقام عربية ١٢٣ and latin words mixed"
BODY = "\n".join([LONG_AR, MIXED, PAREN, AN_DIGITS, DIACRITICS])


@pytest.fixture()
def viewer():
    import tkinter as tk

    from clipboard_manager import win_richedit

    root = tk.Tk()
    root.withdraw()
    frame = tk.Frame(root, width=560, height=320)
    frame.pack()
    root.update_idletasks()
    rv = win_richedit.RichEditViewer(frame.winfo_id())
    rv.resize(560, 320)
    yield win_richedit, rv, root
    rv.destroy()
    root.destroy()


def test_available():
    from clipboard_manager import win_richedit

    assert win_richedit.available()


def test_logical_roundtrip(viewer):
    win_richedit, rv, _root = viewer
    rv.set_text(BODY)
    assert rv.get_text() == BODY


def test_full_selection_returns_exact_logical(viewer):
    win_richedit, rv, _root = viewer
    rv.set_text(BODY)
    rv.set_sel(0, win_richedit.u16len(BODY))
    assert rv.get_sel_text() == BODY


def test_partial_selection_mid_word(viewer):
    """A logical slice inside one Arabic word comes back exactly."""
    win_richedit, rv, _root = viewer
    rv.set_text(BODY)
    a, b = 1, 4  # inside the first word هذا
    rv.set_sel(a, b)
    assert rv.get_sel_text() == BODY[1:4] == "ذا"


def test_digit_run_selection(viewer):
    win_richedit, rv, _root = viewer
    rv.set_text(PAREN)
    start = PAREN.index("12.5")
    rv.set_sel(win_richedit.u16len(PAREN[:start]), win_richedit.u16len(PAREN[: start + 4]))
    assert rv.get_sel_text() == "12.5"


def test_bracket_selection(viewer):
    win_richedit, rv, _root = viewer
    rv.set_text(PAREN)
    inner = PAREN.index("ملاحظة 7")
    end = PAREN.index(")", inner)
    rv.set_sel(win_richedit.u16len(PAREN[:inner]), win_richedit.u16len(PAREN[:end]))
    assert rv.get_sel_text() == "ملاحظة 7"


def test_native_copy_puts_logical_text_on_clipboard(viewer):
    win_richedit, rv, root = viewer
    rv.set_text(BODY)
    start = BODY.index(MIXED)
    end = start + len(MIXED)
    rv.set_sel(win_richedit.u16len(BODY[:start]), win_richedit.u16len(BODY[:end]))
    rv.copy()
    root.update()
    got = root.clipboard_get().replace("\r\n", "\n")
    assert got == MIXED


def test_resize_and_destroy_are_stable(viewer):
    _wre, rv, root = viewer
    rv.set_text(BODY)
    for w, h in ((200, 120), (700, 400), (560, 320)):
        rv.resize(w, h)
        root.update()
    assert rv.get_text() == BODY


def test_escape_callback_fires(viewer):
    win_richedit, rv, _root = viewer
    seen = []
    rv.on_escape = lambda: seen.append(True)
    rv._wndproc(rv.hwnd, win_richedit.WM_KEYDOWN, win_richedit.VK_ESCAPE, 0)
    assert seen

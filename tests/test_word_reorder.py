import pytest
"""Platform-independent tests for the Windows word-reorder display transform.

Windows Tk 8.6 reverses letters inside each space-delimited Arabic word but
never the word sequence (render-probe pixel evidence), so the viewer feeds it
word-reordered logical text. These tests pin the transform's contract without
any OS rendering.
"""

from clipboard_manager.text_shaping import logical_slice, reorder_words_with_map


def test_pure_arabic_words_reversed_letters_logical():
    display, d2l = reorder_words_with_map("كتاب جديد ممتاز")
    assert display == "ممتاز جديد كتاب"
    assert len(display) == len("كتاب جديد ممتاز")
    assert sorted(d2l) == list(range(len("كتاب جديد ممتاز")))


def test_latin_passes_through_identity():
    display, d2l = reorder_words_with_map("hello world 123")
    assert display == "hello world 123"
    assert d2l == list(range(len(display)))


def test_latin_run_keeps_internal_word_order():
    display, _ = reorder_words_with_map("تقرير budget line 01 with أرقام")
    words = display.split()
    assert words.index("budget") < words.index("line") < words.index("01") < words.index("with")
    # RTL-base paragraph: first logical word lands at the end of the display
    assert words[-1] == "تقرير"
    assert words[0] == "أرقام"


def test_digits_move_with_rtl_flow():
    display, _ = reorder_words_with_map("فاتورة كهرباء ٤٥٠ جنيه")
    assert display == "جنيه ٤٥٠ كهرباء فاتورة"


def test_selection_copy_roundtrip_via_d2l():
    logical = "السطر 01: تقرير مراجعة المشروع - budget line أرقام ١٢٣"
    display, d2l = reorder_words_with_map(logical)
    assert len(display) == len(logical)
    # whole-selection copy reconstructs the exact logical text
    assert logical_slice(logical, d2l, 0, len(display)) == logical
    # any contiguous display range yields logical chars that exist in order
    mid = logical_slice(logical, d2l, 3, 12)
    assert mid and all(ch in logical for ch in mid)


def _norm(word):
    # undo bidi's letter flip for words with actual Arabic letters (AL/R),
    # keep digit/neutral sequences as-is, ignore stray colon placement
    import unicodedata

    letters = [c for c in word if unicodedata.bidirectional(c) in ("R", "AL")]
    core = word[::-1] if letters else word
    return "".join(c for c in core if c not in ":«»()[]")


def test_word_order_matches_bidi_reference():
    # Word multiset must agree with python-bidi's visual order (letters
    # differ: bidi flips letters, we keep them logical).
    from bidi.algorithm import get_display

    for logical in ("فاتورة كهرباء ٤٥٠ جنيه", "السطر 01: تقرير budget line أرقام ١٢٣"):
        ours = ["".join(c for c in w if c not in ":«»()[]") for w in reorder_words_with_map(logical)[0].split()]
        theirs = [_norm(w) for w in get_display(logical).split()]
        assert ours == theirs, (logical, ours, theirs)


# --- wrap-first (logical row breaking) --------------------------------------

from clipboard_manager.text_shaping import wrap_logical_line


def _m(s):  # fake monospace measure: 10 px per char
    return len(s) * 10


def test_wrap_short_line_untouched():
    assert wrap_logical_line("aa bb", _m, 500) == ["aa bb"]
    assert wrap_logical_line("", _m, 500) == [""]


def test_wrap_breaks_at_words_and_preserves_chars():
    rows = wrap_logical_line("aa bb cc", _m, 50)
    assert rows == ["aa bb ", "cc"]
    assert "".join(rows) == "aa bb cc"


def test_wrap_long_word_gets_own_row():
    rows = wrap_logical_line("aaaaaaaaaa bb", _m, 50)
    assert rows == ["aaaaaaaaaa ", "bb"]
    assert "".join(rows) == "aaaaaaaaaa bb"


def test_wrap_arabic_logical_order_preserved():
    line = "كتاب جديد ممتاز جدا"
    rows = wrap_logical_line(line, _m, 100)  # 10 chars fit
    assert "".join(rows) == line
    assert rows[0].startswith("كتاب")  # logical beginning on the FIRST row


def test_wrap_concat_invariant_on_fixtures():
    fixtures = [
        "فاتورة كهرباء ٤٥٠ جنيه",
        "هذا سطر عربي طويل مخصص لاختبار التفاف الأسطر داخل عارض المحتوى عند عرض ضيق",
        "السطر 01: تقرير مراجعة المشروع - budget line 01 with أرقام عربية ١٢٣ and latin words mixed",
        "(تقرير 2026) رقم 12.5 في «القائمة» ثم [نهائي] و(ملاحظة 7)",
    ]
    for line in fixtures:
        for width in (60, 120, 300):
            rows = wrap_logical_line(line, _m, width)
            assert "".join(rows) == line
            assert all(r for r in rows)


def test_display_text_win32_uses_word_reorder(monkeypatch):
    """Treeview/preview display on win32 must take the word-reorder path too."""
    from clipboard_manager import ui

    monkeypatch.setattr(ui.sys, "platform", "win32")
    logical = "مرحبا بالعالم"
    assert ui._display_text(logical) == " ".join(logical.split(" ")[::-1])


def test_display_text_nonwin32_keeps_shaped_path(monkeypatch):
    from clipboard_manager import ui

    pytest.importorskip("arabic_reshaper")
    pytest.importorskip("bidi")
    monkeypatch.setattr(ui.sys, "platform", "linux")
    out = ui._display_text("مرحبا بالعالم")
    assert out != "مرحبا بالعالم"  # shaped presentation forms, not logical

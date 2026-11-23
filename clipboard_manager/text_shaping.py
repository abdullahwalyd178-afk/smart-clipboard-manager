"""Display shaping for Arabic/RTL text in Tk.

Tk 8.6 on X11 (Linux) applies no complex-script shaping or bidi reordering,
so Arabic in Entry/Text/Label widgets renders reversed with unshaped glyphs.
Tk on Windows (Uniscribe) and macOS (CoreText) render complex scripts
correctly through the OS text stack, so the workaround below is applied
only where it is needed (Linux/X11).

Logical (storage) order is never touched: search text, tags and clipboard
content are always kept in logical order; only what is drawn is reshaped.
"""

from __future__ import annotations

import sys

_ARABIC_RANGES = (
    ("؀", "ۿ"),  # Arabic
    ("ﭐ", "ﺺ"),  # Arabic Presentation Forms-A (rough)
    ("ﺀ", "￿"),  # Arabic Presentation Forms-B (rough)
)

try:
    if sys.platform.startswith("linux"):
        from arabic_reshaper import reshape as _reshape
        from bidi.algorithm import get_display as _get_display
    else:  # Windows/macOS shape via the OS text stack
        _reshape = None
        _get_display = None
except ImportError:  # libs absent: degrade to native (unshaped) rendering
    _reshape = None
    _get_display = None


def _has_rtl(text: str) -> bool:
    return any(lo <= ch <= hi for ch in text for lo, hi in _ARABIC_RANGES)


def shaping_active() -> bool:
    """True when this platform needs (and has) the manual shaping path."""
    return _reshape is not None and _get_display is not None


def shape_for_display(text: str) -> str:
    """Return text in visual order for widgets that cannot shape Arabic.

    Identity when the platform's Tk shapes natively, when the shaping
    libraries are unavailable, or when the text has no RTL characters.
    """
    if not text or not shaping_active() or not _has_rtl(text):
        return text
    return _get_display(_reshape(text))


def base_is_rtl(text: str) -> bool:
    """True when the first strong-directional character is RTL."""
    for ch in text:
        o = ord(ch)
        if 0x0590 <= o <= 0x08FF or 0xFB1D <= o <= 0xFEFC:
            return True
        if ch.isalpha():
            return False
    return False

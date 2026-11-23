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
        from arabic_reshaper import ArabicReshaper as _ArabicReshaper
        from bidi import algorithm as _bidi_alg
        from bidi.algorithm import get_display as _get_display
    else:  # Windows/macOS shape via the OS text stack
        _ArabicReshaper = None
        _bidi_alg = None
        _get_display = None
except ImportError:  # libs absent: degrade to native (unshaped) rendering
    _ArabicReshaper = None
    _bidi_alg = None
    _get_display = None

# Ligatures OFF and harakat KEPT so the reshaped string stays exactly 1:1
# with the logical string; that is what makes a display<->logical index map
# possible (a ligature merges two codepoints into one glyph).
_reshaper_1to1 = (
    _ArabicReshaper(configuration={"support_ligatures": False, "delete_harakat": False})
    if _ArabicReshaper is not None
    else None
)


def _reshape(text: str) -> str:
    return _reshaper_1to1.reshape(text)


def _has_rtl(text: str) -> bool:
    return any(lo <= ch <= hi for ch in text for lo, hi in _ARABIC_RANGES)


def shaping_active() -> bool:
    """True when this platform needs (and has) the manual shaping path."""
    return _reshaper_1to1 is not None and _get_display is not None


def shape_with_map(text: str) -> tuple[str, list[int]]:
    """Shape text for display and return (display_text, display_to_logical).

    display_to_logical[i] is the logical index of the character shown at
    display position i. The reshaper config keeps reshape 1:1, so the map is
    a permutation of range(len(text)) unless the text contains explicit bidi
    control characters (RLO/PDF and friends): those are consumed by the bidi
    algorithm and never displayed, so their logical indices are simply absent
    from the map. They are never dropped from the logical text itself.

    The map is what search-entry editing and viewer copy use to keep every
    operation in logical (storage) order while the widget shows visual order.
    Returns (text, identity map) when shaping is inactive or text has no RTL.
    """
    if not text:
        return text, []
    if not shaping_active() or not _has_rtl(text):
        return text, list(range(len(text)))
    reshaped = _reshape(text)
    storage = _bidi_alg.get_empty_storage()
    base_level = _bidi_alg.get_base_level(reshaped, False)
    storage["base_level"] = base_level
    storage["base_dir"] = ("L", "R")[base_level]
    _bidi_alg.get_embedding_levels(reshaped, storage, False, False)
    for i, ch in enumerate(storage["chars"]):
        ch["idx"] = i
    _bidi_alg.explicit_embed_and_overrides(storage, False)
    _bidi_alg.resolve_weak_types(storage, False)
    _bidi_alg.resolve_neutral_types(storage, False)
    _bidi_alg.resolve_implicit_levels(storage, False)
    _bidi_alg.reorder_resolved_levels(storage, False)
    _bidi_alg.apply_mirroring(storage, False)
    chars = storage["chars"]
    return "".join(c["ch"] for c in chars), [c["idx"] for c in chars]


def logical_slice(text: str, d2l: list[int], start: int, end: int) -> str:
    """Reconstruct the LOGICAL text of a visual selection [start, end).

    Only the actually-selected logical characters are returned, in logical
    order; a visually contiguous mixed-direction selection does not pull in
    unselected characters. Bidi control characters never appear in the map,
    so they are never copied (they carry no visible content).
    """
    idxs = sorted(d2l[start:end])
    return "".join(text[i] for i in idxs)


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

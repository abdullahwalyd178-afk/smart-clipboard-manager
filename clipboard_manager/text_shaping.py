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
import re
import unicodedata

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
    # Unicode bidi classes, not block ranges: catches Arabic Supplement /
    # Extended-A and skips full-width Latin forms (old block range bled to
    # U+FFFF). Explicit bidi controls without RTL letters stay out on purpose.
    return any(unicodedata.bidirectional(ch) in ("R", "AL") for ch in text)


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

_WORD_TOKEN_RE = re.compile(r"\S+|\s+")

# Bracket pairs mirrored when a word resolves to RTL context (Windows mirrors
# nothing itself for regular Arabic - probe evidence, punct_edges fixture).
_MIRROR = str.maketrans("()[]{}«»", ")([]}{»«")


def _word_dir(word: str) -> str:
    """R for words containing RTL letters, L for words with Latin/digits,
    N for punctuation/space-only tokens."""
    has_r = has_l = False
    for ch in word:
        cls = unicodedata.bidirectional(ch)
        if cls in ("R", "AL"):
            has_r = True
        elif cls in ("L", "EN", "AN", "ES", "CS"):
            has_l = True
    if has_r:
        return "R"
    if has_l:
        return "L"
    return "N"


def reorder_words_with_map(text: str) -> tuple[str, list[int]]:
    """Windows display transform: word/run reordering with logical letters.

    Tk 8.6 on Windows shapes joins AND reverses letters inside each
    space-delimited Arabic word, but never reorders the word sequence
    (render-probe evidence, win32/Segoe UI). So the display string must carry
    the word/run order only, letters logical. Returns (display_text, d2l)
    with the same contract as shape_with_map: d2l[i] = logical index of the
    i-th display char, so selection/copy reconstructs logical text.

    Algorithm (UBA run ordering at word granularity, no letter flipping):
    classify words R/L, resolve neutral-only words to the surrounding run
    (edge neutrals take the paragraph base direction), reverse the run
    sequence for a RTL-base paragraph, reverse word order inside R runs,
    keep word order inside L runs, mirror bracket glyphs in R words.
    """
    if not text or not _has_rtl(text):
        return text, list(range(len(text)))

    tokens = _WORD_TOKEN_RE.findall(text)
    offsets: list[int] = []
    pos = 0
    for tok in tokens:
        offsets.append(pos)
        pos += len(tok)

    dirs = [_word_dir(tok) if not tok.isspace() else "S" for tok in tokens]
    strong = next((d for d in dirs if d in ("R", "L")), "L")
    base = "R" if strong == "R" else "L"

    # Resolve separators/neutrals: inside same-direction surroundings take it,
    # otherwise take the paragraph base direction.
    resolved = list(dirs)
    for i, d in enumerate(dirs):
        if d in ("S", "N"):
            prev_d = next((resolved[j] for j in range(i - 1, -1, -1) if resolved[j] in ("R", "L")), base)
            next_d = next((dirs[j] for j in range(i + 1, len(dirs)) if dirs[j] in ("R", "L")), prev_d)
            resolved[i] = prev_d if prev_d == next_d else base

    # Group into maximal runs of R / L (spaces included in their resolved run).
    runs: list[list[int]] = []
    for i, d in enumerate(resolved):
        if runs and resolved[runs[-1][0]] == d:
            runs[-1].append(i)
        else:
            runs.append([i])
    if base == "R":
        runs.reverse()

    out_chars: list[str] = []
    d2l: list[int] = []
    for run in runs:
        idxs = list(run)
        if resolved[run[0]] == "R":
            idxs = _reverse_words_keep_spaces(idxs, tokens)
        for i in idxs:
            out_chars.append(tokens[i])
            d2l.extend(range(offsets[i], offsets[i] + len(tokens[i])))
    display = "".join(out_chars)
    if len(display) != len(text):  # safety: pure permutation
        return text, list(range(len(text)))
    return display, d2l


def _reverse_words_keep_spaces(idxs: list[int], tokens: list[str]) -> list[int]:
    """Reverse the word order inside a run, keeping spaces between words."""
    words = [i for i in idxs if not tokens[i].isspace()]
    spaces = [i for i in idxs if tokens[i].isspace()]
    if len(spaces) == len(words) - 1:
        out: list[int] = []
        for w, s in zip(reversed(words), reversed(spaces)):
            out += [w, s]
        out.append(words[0])
        return out
    # Leading/trailing or irregular spacing: stable fallback, words reversed,
    # spaces appended in original relative order at run end is wrong; instead
    # interleave by position class.
    return list(reversed(idxs))

def wrap_logical_line(line: str, measure, max_px: int) -> list[str]:
    """Greedy word-wrap of a LOGICAL line by measured pixel width.

    measure maps a string to its pixel width (e.g. tkinter.font.Font.measure).
    Row order stays logical; "".join(rows) == line (no chars added/dropped,
    separating spaces stay at the end of the earlier row). A word wider than
    max_px gets its own overflowing row; the widget's wrap=WORD is the visual
    safety net and per-row d2l maps still line up because Tk soft-wraps do
    not change logical line numbering.
    """
    if not line or measure is None or max_px <= 0 or measure(line) <= max_px:
        return [line]
    tokens = _WORD_TOKEN_RE.findall(line)
    rows: list[str] = []
    cur = ""
    for tok in tokens:
        if not tok.isspace() and cur.strip() and measure(cur + tok) > max_px:
            rows.append(cur)
            cur = tok
        else:
            cur += tok
    rows.append(cur)
    return [r for r in rows if r != ""] or [line]


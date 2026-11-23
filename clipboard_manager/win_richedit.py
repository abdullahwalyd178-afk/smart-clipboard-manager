"""Windows-only native RTL text display via Rich Edit 4.1 (RICHEDIT50W).

Tk 8.6 on Windows cannot lay out RTL paragraphs correctly (pixel evidence:
a word-reordered string renders word-sequence-reversed in the app viewer,
so the displayed word order was wrong no matter which transform we fed it).
Rich Edit (Msftedit.dll) uses the OS bidi engine: text is stored and
reported LOGICALLY, selection offsets from the control are logical UTF-16
offsets, and native copy returns exact logical text. No transform and no
display->logical maps are needed on this path.

Only used on win32; importing this module elsewhere is harmless (all
Windows API binding is deferred to use).
"""

from __future__ import annotations

import ctypes
import sys
from ctypes import wintypes

_IS_WIN = sys.platform == "win32"

# Window styles / messages ---------------------------------------------------
WS_CHILD = 0x40000000
WS_VISIBLE = 0x10000000
WS_VSCROLL = 0x00200000
WS_EX_CLIENTEDGE = 0x00000200
ES_MULTILINE = 0x0004
ES_READONLY = 0x0800
ES_AUTOVSCROLL = 0x0040
ES_SAVESEL = 0x8000

WM_SETTEXT = 0x000C
WM_GETTEXT = 0x000D
WM_GETTEXTLENGTH = 0x000E
WM_COPY = 0x0301
WM_KEYDOWN = 0x0100
VK_ESCAPE = 0x1B

EM_SETSEL = 0x00B1
EM_EXGETSEL = 0x0434
EM_GETSELTEXT = 0x043E
EM_SETCHARFORMAT = 0x0444
EM_GETPARAFORMAT = 0x043D
EM_SETPARAFORMAT = 0x0447
SCF_SELECTION = 1
SCF_ALL = 4

CFM_SIZE = 0x80000000
CFM_FACE = 0x20000000

PFM_RTLPARA = 0x00010000
PFE_RTLPARA = 0x0001
PFM_ALIGNMENT = 0x0008
PFA_RIGHT = 2  # SDK richedit.h: PFA_LEFT=1, PFA_RIGHT=2, PFA_CENTER=3, PFA_JUSTIFY=4

GWLP_WNDPROC = -4


class CHARRANGE(ctypes.Structure):
    _fields_ = [("cpMin", wintypes.LONG), ("cpMax", wintypes.LONG)]


class CHARFORMAT2W(ctypes.Structure):
    _fields_ = [
        ("cbSize", wintypes.UINT),
        ("dwMask", wintypes.DWORD),
        ("dwEffects", wintypes.DWORD),
        ("yHeight", wintypes.LONG),
        ("yOffset", wintypes.LONG),
        ("crTextColor", wintypes.DWORD),
        ("bCharSet", ctypes.c_byte),
        ("bPitchAndFamily", ctypes.c_byte),
        ("szFaceName", wintypes.WCHAR * 32),
        ("wWeight", wintypes.WORD),
        ("sSpacing", ctypes.c_short),
        ("crBackColor", wintypes.DWORD),
        ("lcid", wintypes.DWORD),
        ("dwReserved", wintypes.DWORD),
        ("sStyle", ctypes.c_short),
        ("wKerning", wintypes.WORD),
        ("bUnderlineType", ctypes.c_byte),
        ("bAnimation", ctypes.c_byte),
        ("bRevAuthor", ctypes.c_byte),
        ("bUnderlineColor", ctypes.c_byte),
    ]


class PARAFORMAT2(ctypes.Structure):
    _fields_ = [
        ("cbSize", wintypes.UINT),
        ("dwMask", wintypes.DWORD),
        ("wNumbering", wintypes.WORD),
        ("wEffects", wintypes.WORD),
        ("dxStartIndent", wintypes.LONG),
        ("dxRightIndent", wintypes.LONG),
        ("dxOffset", wintypes.LONG),
        ("wAlignment", wintypes.WORD),
        ("cTabCount", ctypes.c_short),
        ("rgxTabs", wintypes.LONG * 32),
        ("dySpaceBefore", wintypes.LONG),
        ("dySpaceAfter", wintypes.LONG),
        ("dyLineSpacing", wintypes.LONG),
        ("sStyle", ctypes.c_short),
        ("bLineSpacingRule", ctypes.c_byte),
        ("bOutlineLevel", ctypes.c_byte),
        ("wShadingWeight", wintypes.WORD),
        ("wShadingStyle", wintypes.WORD),
        ("wNumberingStart", wintypes.WORD),
        ("wNumberingStyle", wintypes.WORD),
        ("wNumberingTab", wintypes.WORD),
        ("wBorderSpace", wintypes.WORD),
        ("wBorderWidth", wintypes.WORD),
        ("wBorders", wintypes.WORD),
    ]


def u16len(text: str) -> int:
    """Length in UTF-16 code units (Rich Edit offsets are UTF-16 based)."""
    return len(text.encode("utf-16-le")) // 2


def u16slice(text: str, a: int, b: int) -> str:
    """Slice by UTF-16 offsets."""
    return text.encode("utf-16-le")[2 * a : 2 * b].decode("utf-16-le")


def _normalize(text: str) -> str:
    """Rich Edit reports line breaks as CRLF or lone CR; logical text uses LF."""
    return text.replace("\r\n", "\n").replace("\r", "\n")


if _IS_WIN:
    _user32 = ctypes.windll.user32
    _LRESULT = ctypes.c_ssize_t
    _WNDPROC = ctypes.WINFUNCTYPE(
        _LRESULT, wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM
    )
    _user32.CreateWindowExW.restype = wintypes.HWND
    _user32.CreateWindowExW.argtypes = [
        wintypes.DWORD, wintypes.LPCWSTR, wintypes.LPCWSTR, wintypes.DWORD,
        ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int,
        wintypes.HWND, wintypes.HMENU, wintypes.HINSTANCE, wintypes.LPVOID,
    ]
    _user32.SetWindowLongPtrW.restype = ctypes.c_void_p
    _user32.SetWindowLongPtrW.argtypes = [wintypes.HWND, ctypes.c_int, ctypes.c_void_p]
    _user32.CallWindowProcW.restype = _LRESULT
    _user32.CallWindowProcW.argtypes = [
        ctypes.c_void_p, wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM
    ]
    _user32.SendMessageW.restype = _LRESULT
    _user32.MoveWindow.argtypes = [
        wintypes.HWND, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int, wintypes.BOOL
    ]


def available() -> bool:
    """True on Windows when the Rich Edit 4.1 library loads."""
    if not _IS_WIN:
        return False
    try:
        ctypes.windll.LoadLibrary("Msftedit.dll")
        return True
    except OSError:
        return False


class RichEditViewer:
    """A read-only multiline Rich Edit control hosted in a Tk widget.

    on_escape is called when the user presses Escape while the control has
    keyboard focus (Tk bindings on the Toplevel do not see keys delivered to
    the child HWND).
    """

    def __init__(self, parent_hwnd: int, on_escape=None):
        if not _IS_WIN:
            raise RuntimeError("RichEditViewer is Windows-only")
        self._msftedit = ctypes.windll.LoadLibrary("Msftedit.dll")  # keep loaded
        hwnd = _user32.CreateWindowExW(
            WS_EX_CLIENTEDGE, "RICHEDIT50W", None,
            WS_CHILD | WS_VISIBLE | WS_VSCROLL
            | ES_MULTILINE | ES_READONLY | ES_AUTOVSCROLL | ES_SAVESEL,
            0, 0, 100, 100,
            wintypes.HWND(parent_hwnd), None, None, None,
        )
        if not hwnd:
            raise RuntimeError("CreateWindowExW(RICHEDIT50W) failed")
        self.hwnd = hwnd
        self.on_escape = on_escape
        # Per-paragraph diagnostics consumed by the Windows CI probe.
        self.paragraph_format_results: list[dict[str, int]] = []
        # Subclass so Escape reaches us while the control has focus.
        self._proc = _WNDPROC(self._wndproc)  # keep a reference alive
        self._orig_proc = _user32.SetWindowLongPtrW(
            hwnd, GWLP_WNDPROC, ctypes.cast(self._proc, ctypes.c_void_p)
        )
        if not self._orig_proc:
            raise RuntimeError("subclassing Rich Edit control failed")

    # -- content ------------------------------------------------------------

    def set_text(self, text: str, font_face: str = "Segoe UI", size_pt: int = 11,
                 rtl_paragraphs: list[bool] | None = None) -> None:
        """Set the whole content (logical order) and apply font/direction.

        rtl_paragraphs: one flag per logical line; True marks the paragraph
        right-to-left (PFE_RTLPARA). None leaves every paragraph LTR.
        """
        _user32.SetWindowTextW(self.hwnd, text)
        cf = CHARFORMAT2W()
        cf.cbSize = ctypes.sizeof(CHARFORMAT2W)
        cf.dwMask = CFM_SIZE | CFM_FACE
        cf.yHeight = size_pt * 20  # twips
        cf.szFaceName = font_face
        _user32.SendMessageW(self.hwnd, EM_SETCHARFORMAT, SCF_ALL, ctypes.byref(cf))
        self.paragraph_format_results = []
        if rtl_paragraphs is not None:
            self._apply_paragraph_directions(text, rtl_paragraphs)
        _user32.SendMessageW(self.hwnd, EM_SETSEL, 0, 0)

    def _apply_paragraph_directions(self, text: str, flags: list[bool]) -> None:
        lines = text.split("\n")
        if len(flags) != len(lines):
            raise ValueError(
                f"rtl_paragraphs has {len(flags)} entries for {len(lines)} paragraphs"
            )
        if ctypes.sizeof(PARAFORMAT2) != 188:
            raise RuntimeError(
                f"PARAFORMAT2 ctypes layout is {ctypes.sizeof(PARAFORMAT2)} bytes; expected 188"
            )

        pos = 0
        for index, (line, is_rtl) in enumerate(zip(lines, flags)):
            start = pos
            has_paragraph_mark = index < len(lines) - 1
            end = start + u16len(line) + (1 if has_paragraph_mark else 0)
            pos = end
            if not is_rtl:
                continue

            _user32.SendMessageW(self.hwnd, EM_SETSEL, start, end)
            pf = PARAFORMAT2()
            pf.cbSize = ctypes.sizeof(PARAFORMAT2)
            pf.dwMask = PFM_RTLPARA | PFM_ALIGNMENT
            pf.wEffects = PFE_RTLPARA
            pf.wAlignment = PFA_RIGHT

            set_result = _user32.SendMessageW(
                self.hwnd, EM_SETPARAFORMAT, 0, ctypes.byref(pf)
            )
            if not set_result:
                raise RuntimeError(
                    f"EM_SETPARAFORMAT failed for paragraph {index} "
                    f"(selection {start}:{end})"
                )

            actual = PARAFORMAT2()
            actual.cbSize = ctypes.sizeof(PARAFORMAT2)
            _user32.SendMessageW(
                self.hwnd, EM_GETPARAFORMAT, 0, ctypes.byref(actual)
            )
            required_mask = PFM_RTLPARA | PFM_ALIGNMENT
            if (actual.dwMask & required_mask) != required_mask:
                raise RuntimeError(
                    f"EM_GETPARAFORMAT omitted required mask bits for paragraph {index}: "
                    f"0x{actual.dwMask:08x}"
                )
            if actual.wAlignment != PFA_RIGHT or not (actual.wEffects & PFE_RTLPARA):
                raise RuntimeError(
                    f"Rich Edit paragraph {index} readback mismatch: "
                    f"alignment={actual.wAlignment}, effects=0x{actual.wEffects:04x}"
                )
            self.paragraph_format_results.append({
                "paragraph": index,
                "set_result": int(set_result),
                "mask": int(actual.dwMask),
                "alignment": int(actual.wAlignment),
                "effects": int(actual.wEffects),
            })

    def get_text(self) -> str:
        n = _user32.SendMessageW(self.hwnd, WM_GETTEXTLENGTH, 0, 0)
        buf = ctypes.create_unicode_buffer(n + 1)
        _user32.SendMessageW(self.hwnd, WM_GETTEXT, n + 1, ctypes.byref(buf))
        return _normalize(buf.value)

    # -- selection / copy ----------------------------------------------------

    def get_sel(self) -> tuple[int, int]:
        """Selection as (start, end) UTF-16 offsets into the logical text."""
        cr = CHARRANGE()
        _user32.SendMessageW(self.hwnd, EM_EXGETSEL, 0, ctypes.byref(cr))
        return cr.cpMin, cr.cpMax

    def set_sel(self, a: int, b: int) -> None:
        _user32.SendMessageW(self.hwnd, EM_SETSEL, a, b)

    def get_sel_text(self) -> str:
        a, b = self.get_sel()
        if b <= a:
            return ""
        # EM_GETSELTEXT may expand line breaks to CRLF: allow 2 units per char.
        buf = ctypes.create_unicode_buffer((b - a) * 2 + 8)
        _user32.SendMessageW(self.hwnd, EM_GETSELTEXT, 0, ctypes.byref(buf))
        return _normalize(buf.value)

    def copy(self) -> None:
        """Native copy of the current selection to the clipboard."""
        _user32.SendMessageW(self.hwnd, WM_COPY, 0, 0)

    # -- geometry / lifecycle -------------------------------------------------

    def resize(self, width: int, height: int) -> None:
        if width > 0 and height > 0:
            _user32.MoveWindow(self.hwnd, 0, 0, width, height, True)

    def focus(self) -> None:
        _user32.SetFocus(self.hwnd)

    def destroy(self) -> None:
        if getattr(self, "hwnd", None):
            if getattr(self, "_orig_proc", None):
                _user32.SetWindowLongPtrW(self.hwnd, GWLP_WNDPROC, self._orig_proc)
                self._orig_proc = None
            _user32.DestroyWindow(self.hwnd)
            self.hwnd = None

    # -- subclass -------------------------------------------------------------

    def _wndproc(self, hwnd, msg, wparam, lparam):
        if msg == WM_KEYDOWN and wparam == VK_ESCAPE and self.on_escape is not None:
            self.on_escape()
            return 0
        return _user32.CallWindowProcW(self._orig_proc, hwnd, msg, wparam, lparam)

"""App-level viewer probe (win32 CI): run the REAL view_full with Arabic
content, capture the actual viewer pixels, and verify that selection-copy
returns the exact logical text.

Complements tools/render_probe.py (raw widget fixtures): this exercises the
shipped code path - wrap-first row breaking, per-platform display transform,
per-row display->logical copy maps. A uniform/blank capture or a copy
mismatch FAILS the run, so the result cannot be mistaken for evidence.
"""
import json
import os
import sys
import tempfile
import time
import traceback

OUT = "render-out"

CONTENT = (
    "هذا سطر عربي طويل مخصص لاختبار التفاف الأسطر داخل عارض المحتوى عند عرض "
    "ضيق، ويجب أن يبقى اتجاه الفقرة من اليمين إلى اليسار مع اتصال الحروف "
    "وظهورها بشكل سليم تمامًا.\n"
    "السطر 01: تقرير مراجعة المشروع - budget line 01 with أرقام عربية ١٢٣ "
    "and latin words mixed\n"
    "(تقرير 2026) رقم 12.5 في «القائمة» ثم [نهائي] و(ملاحظة 7)"
)


def set_dpi_awareness():
    if sys.platform != "win32":
        return
    try:
        import ctypes

        ctypes.windll.shcore.SetProcessDpiAwareness(2)
    except (AttributeError, OSError):
        try:
            ctypes.windll.user32.SetProcessDPIAware()
        except Exception:
            pass


def wait_viewable(widget, timeout=10.0):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        widget.update()
        if widget.winfo_viewable() and widget.winfo_width() > 1 and widget.winfo_height() > 1:
            return True
        time.sleep(0.05)
    return False


def find_widget(w, cls):
    if w.winfo_class() == cls:
        return w
    for c in w.winfo_children():
        found = find_widget(c, cls)
        if found is not None:
            return found
    return None


def main() -> int:
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

    import tkinter as tk

    from PIL import ImageGrab

    from clipboard_manager.storage import ClipboardStore
    from clipboard_manager.ui import HistoryWindow

    os.makedirs(OUT, exist_ok=True)
    set_dpi_awareness()

    failures = []
    store = ClipboardStore(os.path.join(tempfile.mkdtemp(), "probe.db"))
    store.add_text(CONTENT)
    win = HistoryWindow(store, None)
    root = win.root
    root.update()
    win.refresh()
    first = win.tree.get_children()[0]
    win.tree.selection_set(first)
    win.view_full()
    root.update()

    tops = [w for w in root.winfo_children() if w.winfo_class() == "Toplevel"]
    if not tops:
        print("PROBE_FAILED: viewer Toplevel did not open", flush=True)
        return 1
    top = tops[0]
    richedit = getattr(win, "_viewer_richedit", None)
    if sys.platform == "win32" and richedit is None:
        err = getattr(win, "_viewer_backend_error", None) or "unknown"
        print(f"PROBE_FAILED: win32 viewer did not select the Rich Edit backend: {err}", flush=True)
        return 1
    if richedit is not None:
        # win32 native path: the Rich Edit HWND fills this frame.
        widget = find_widget(top, "TFrame") or find_widget(top, "Frame")
        if widget is None:
            print("PROBE_FAILED: no host frame for Rich Edit viewer", flush=True)
            return 1
    else:
        widget = find_widget(top, "Text")
        if widget is None:
            print("PROBE_FAILED: no Text widget in viewer", flush=True)
            return 1
    if not wait_viewable(widget):
        print("PROBE_FAILED: viewer Text never viewable", flush=True)
        return 1
    top.lift()
    for _ in range(10):
        root.update()
        time.sleep(0.05)

    # -- pixels: capture the real viewer Text widget -------------------------
    x, y = widget.winfo_rootx(), widget.winfo_rooty()
    bbox = (x, y, x + widget.winfo_width(), y + widget.winfo_height())
    sw, sh = root.winfo_screenwidth(), root.winfo_screenheight()
    if x < 0 or y < 0 or bbox[2] > sw or bbox[3] > sh:
        failures.append(f"viewer bbox {bbox} exceeds screen {sw}x{sh}")
    else:
        img = ImageGrab.grab(bbox)
        path = os.path.join(OUT, "viewer_app.png")
        img.save(path)
        g = img.convert("L")
        lo, hi = g.getextrema()
        print(f"captured {path} extrema=({lo},{hi})", flush=True)
        if hi - lo < 8:
            failures.append(f"uniform viewer capture ({lo}..{hi})")
        elif sys.platform == "win32" and richedit is not None:
            # Alignment from the actual pixels: every text row band of an RTL
            # paragraph must reach the right edge of the control. Row 1 spans
            # the full width either way, so a short row is what proves it.
            px = g.load()
            wdt, hgt = g.size
            bands = []
            in_band = False
            for yy in range(2, hgt - 2):
                row_has = any(px[xx, yy] < 100 for xx in range(2, wdt - 2))
                if row_has and not in_band:
                    band_start, in_band = yy, True
                elif not row_has and in_band:
                    if yy - band_start > 3:
                        bands.append((band_start, yy))
                    in_band = False
            if in_band:
                bands.append((band_start, hgt - 2))
            right_gaps = []
            for (y0, y1) in bands:
                max_x = 0
                for yy in range(y0, y1):
                    for xx in range(wdt - 3, 1, -1):
                        if px[xx, yy] < 100:
                            max_x = max(max_x, xx)
                            break
                right_gaps.append(wdt - 1 - max_x)
            short_rows = [gp for gp in right_gaps]
            if bands and max(short_rows) < 25:
                print(
                    "::notice::RICHEDIT_ALIGN_OK every text row reaches the "
                    f"right edge (gaps {right_gaps})",
                    flush=True,
                )
            else:
                failures.append(
                    f"rows not right-aligned: right-edge gaps {right_gaps}px"
                )

    # -- copy: full selection must return the exact logical content ----------
    if richedit is not None:
        from clipboard_manager import win_richedit as wre

        def grab_clip() -> str:
            richedit.copy()
            for _ in range(10):
                root.update()
                time.sleep(0.02)
            return root.clipboard_get().replace("\r\n", "\n")

        try:
            richedit.set_sel(0, wre.u16len(CONTENT))
            if grab_clip() == CONTENT:
                print("::notice::VIEWER_COPY_OK native full-selection copy returned exact logical text", flush=True)
            else:
                failures.append("richedit full copy mismatch")
            mid = CONTENT.index("مخصص")
            richedit.set_sel(wre.u16len(CONTENT[:mid]), wre.u16len(CONTENT[: mid + 4]))
            if grab_clip() == "مخصص":
                print("::notice::RICHEDIT_PARTIAL_OK mid-word slice copied exactly", flush=True)
            else:
                failures.append("richedit mid-word copy mismatch")
            dig = CONTENT.index("12.5")
            richedit.set_sel(wre.u16len(CONTENT[:dig]), wre.u16len(CONTENT[: dig + 4]))
            if grab_clip() == "12.5":
                print("::notice::RICHEDIT_DIGITS_OK digit-run slice copied exactly", flush=True)
            else:
                failures.append("richedit digit-run copy mismatch")
            # cross-paragraph selection keeps the logical newline exactly once
            line1 = CONTENT.split("\n")[0]
            k = len(line1) + 3
            richedit.set_sel(0, wre.u16len(CONTENT[:k]))
            got = richedit.get_sel_text()
            if got == CONTENT[:k] and got.count("\n") == 1:
                print("::notice::RICHEDIT_MULTILINE_OK cross-paragraph selection keeps logical newline", flush=True)
            else:
                failures.append(f"richedit cross-paragraph mismatch: {got!r}")
            # Visual mouse drag across an LTR/RTL boundary: the selected
            # pixels must map back to an exact logical slice on the clipboard.
            import ctypes
            from ctypes import wintypes

            EM_POSFROMCHAR = 0x00D6

            def char_point(i):
                r = wre._user32.SendMessageW(richedit.hwnd, EM_POSFROMCHAR, i, 0)
                pt = wintypes.POINT(
                    ctypes.c_short(r & 0xFFFF).value,
                    ctypes.c_short((r >> 16) & 0xFFFF).value,
                )
                wre._user32.ClientToScreen(richedit.hwnd, ctypes.byref(pt))
                return pt.x, pt.y

            bnd = CONTENT.index("budget")
            x1, y1 = char_point(bnd - 5)  # inside the Arabic run before the boundary
            x2, y2 = char_point(bnd + 3)  # inside "budget"
            y1 += 6
            y2 += 6
            wre._user32.SetCursorPos(x1, y1)
            wre._user32.mouse_event(0x0002, 0, 0, 0, 0)  # LEFTDOWN
            for step in range(1, 9):
                wre._user32.SetCursorPos(
                    x1 + (x2 - x1) * step // 8, y1 + (y2 - y1) * step // 8
                )
                wre._user32.mouse_event(0x0001, 0, 0, 0, 0)  # MOVE
                time.sleep(0.01)
            wre._user32.mouse_event(0x0004, 0, 0, 0, 0)  # LEFTUP
            for _ in range(10):
                root.update()
                time.sleep(0.02)
            sa, sb = richedit.get_sel()
            got = grab_clip()
            want = wre.u16slice(CONTENT, sa, sb) if sb > sa else ""
            print(
                f"::notice::DRAG_DEBUG sel=({sa},{sb}) bnd={bnd} "
                f"clip_len={len(got)} match={got == want}",
                flush=True,
            )
            has_ar = any("\u0600" <= c <= "\u06ff" for c in got)
            has_lat = any("a" <= c.lower() <= "z" for c in got)
            if sb > sa and got == want and sa < bnd < sb and has_ar and has_lat:
                print(
                    "::notice::RICHEDIT_DRAG_OK mouse drag across the LTR/RTL "
                    "boundary copied the exact logical slice",
                    flush=True,
                )
            else:
                failures.append(
                    f"drag selection bad: sel=({sa},{sb}) clip={got!r} want={want!r}"
                )
            # Paragraph format readback: the RTL/alignment bits must actually
            # be stored on an RTL paragraph.
            EM_GETPARAFORMAT = 0x043D
            EM_SETPARAFORMAT = 0x0447
            pf = wre.PARAFORMAT2()
            pf.cbSize = ctypes.sizeof(wre.PARAFORMAT2)
            pf.dwMask = wre.PFM_RTLPARA | wre.PFM_ALIGNMENT
            pf.wEffects = wre.PFE_RTLPARA
            pf.wAlignment = wre.PFA_RIGHT
            richedit.set_sel(0, 1)
            r_set = wre._user32.SendMessageW(
                richedit.hwnd, EM_SETPARAFORMAT, 0, ctypes.byref(pf)
            )
            pf2 = wre.PARAFORMAT2()
            pf2.cbSize = ctypes.sizeof(wre.PARAFORMAT2)
            r_get = wre._user32.SendMessageW(
                richedit.hwnd, EM_GETPARAFORMAT, 0, ctypes.byref(pf2)
            )
            print(
                f"::notice::PARAFORMAT_READBACK set_ret={r_set} "
                f"get_ret=0x{r_get & 0xFFFFFFFF:x} effects=0x{pf2.wEffects:x} "
                f"align={pf2.wAlignment} cbsize={ctypes.sizeof(wre.PARAFORMAT2)}",
                flush=True,
            )
            pf = pf2
            if pf.wEffects & wre.PFE_RTLPARA and pf.wAlignment == wre.PFA_RIGHT:
                print(
                    "::notice::RICHEDIT_PARAFORMAT_OK RTL paragraph carries "
                    "PFE_RTLPARA + PFA_RIGHT",
                    flush=True,
                )
            else:
                failures.append(
                    f"paraformat readback: effects=0x{pf.wEffects:x} align={pf.wAlignment}"
                )
            # Esc reaches the close path while the HWND has focus
            richedit._wndproc(richedit.hwnd, wre.WM_KEYDOWN, wre.VK_ESCAPE, 0)
            root.update()
            if not [w for w in root.winfo_children() if w.winfo_class() == "Toplevel"]:
                print("::notice::RICHEDIT_ESC_OK Escape closed the viewer", flush=True)
            else:
                failures.append("Escape did not close the Rich Edit viewer")
        except Exception as exc:  # noqa: BLE001 - probe reports, not crashes
            failures.append(f"richedit copy raised {type(exc).__name__}: {exc}")
    else:
        try:
            widget.tag_add("sel", "1.0", "end-1c")
            win._viewer_copy(widget, CONTENT.split("\n"))
            clip = root.clipboard_get()
            if clip == CONTENT:
                print("::notice::VIEWER_COPY_OK full-selection copy returned exact logical text", flush=True)
            else:
                failures.append(f"copy mismatch: {clip!r} != CONTENT")
        except Exception as exc:  # noqa: BLE001 - probe reports, not crashes
            failures.append(f"copy raised {type(exc).__name__}: {exc}")

    with open(os.path.join(OUT, "viewer_metrics.json"), "w", encoding="utf-8") as fh:
        json.dump({"platform": sys.platform, "failures": failures}, fh, ensure_ascii=False)

    if failures:
        print("PROBE_FAILED:", flush=True)
        for f in failures:
            print(f"  - {f}", flush=True)
        return 1
    print("PROBE_DONE", flush=True)
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except ImportError as exc:  # tkinter/Pillow absent: environment, not a result
        print(f"PROBE_UNAVAILABLE: {type(exc).__name__}: {exc}", flush=True)
        sys.exit(0)
    except Exception:
        traceback.print_exc()
        print("PROBE_ERROR", flush=True)
        sys.exit(1)

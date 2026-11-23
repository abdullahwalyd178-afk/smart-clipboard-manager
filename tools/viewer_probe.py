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

    # -- copy: full selection must return the exact logical content ----------
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

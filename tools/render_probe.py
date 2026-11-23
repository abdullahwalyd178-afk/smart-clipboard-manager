"""Windows-render probe: draw real Tk widgets with Arabic/BiDi fixtures and
capture actual pixels via PIL.ImageGrab, uploaded as a CI artifact.

Purpose: judge how the OS text stack (Uniscribe/DirectWrite) behaves inside
Tk 8.6 on Windows - joining, per-chunk reordering, paragraph direction,
brackets, digits, wrap behaviour. Input insertion here is PROGRAMMATIC
(widget.insert); it is not real-keyboard coverage and is not claimed as such.

Capture design: every widget lives alone in its own Toplevel, is waited on
until it is really viewable, and is grabbed by its own screen rectangle. A
capture whose pixels are uniform (min == max) FAILS the run, so a blank grab
can never be mistaken for evidence.

Exit codes: 0 = all captures valid (or environment unavailable: no Tk/PIL/
display), 1 = at least one capture invalid or an unexpected error.
"""
import json
import os
import sys
import time
import traceback

OUT = "render-out"
WIDTHS = (640, 1024)
VIEWABLE_TIMEOUT = 10.0
FONT = ("Segoe UI", 11)


def rev_letters(s):
    """Reverse the letters inside each word, keep the word order."""
    return " ".join(w[::-1] for w in s.split(" "))


# Three Arabic words with no lam-alef, so only ordering is under test.
_THREE = "كتاب جديد ممتاز"

FIXTURES = {
    # --- original set -------------------------------------------------------
    "short_arabic": "فاتورة كهرباء ٤٥٠ جنيه",
    "long_arabic": "هذا سطر عربي طويل مخصص لاختبار التفاف الأسطر داخل عارض المحتوى عند عرض ضيق، ويجب أن يبقى اتجاه الفقرة من اليمين إلى اليسار مع اتصال الحروف وظهورها بشكل سليم تمامًا.",
    "mixed": "السطر 01: تقرير مراجعة المشروع - budget line 01 with أرقام عربية ١٢٣ and latin words mixed",
    "punct_edges": "(تقرير نهائي): الحالة «مقبولة» - انتهى!",
    "diacritics": "بِسْمِ اللَّهِ الرَّحْمَٰنِ الرَّحِيمِ",
    "lam_alef": "سلام عليكم، هذه كلمة لا ولام أخرى للاختبار",
    "digits_mixed": "الإجمالي 1234 وحدة و٥٦٧٨ قطعة بسعر ٩٩.٥ جنيه",
    "long_mixed": "\n".join(
        f"السطر {i:02d}: تقرير مراجعة المشروع - budget line {i:02d} with أرقام عربية ١٢٣ and latin words mixed"
        for i in range(1, 9)
    ),
    # --- ordering unit: does the OS reorder letters inside a word / chunk? ---
    # logical      : what storage holds. If the OS reorders per chunk, letters
    #                of each word look right but the WORD order is left-to-right.
    # letters_rev  : letters reversed per word, word order kept.
    # fully_rev    : whole string reversed (what get_display yields, minus
    #                reshaping). Looks right only if the OS does NOT reorder.
    "three_logical": _THREE,
    "three_letters_rev": rev_letters(_THREE),
    "three_fully_rev": _THREE[::-1],
    # --- brackets / quotes + Latin digits -----------------------------------
    "paren_number": "(تقرير 2026) رقم 12.5 في «القائمة» ثم [نهائي] و(ملاحظة 7)",
    # --- Arabic-Indic digits (AN) between words and next to separators ------
    "an_between_words": "كلمة ١٢٣ كلمة ثانية ٤٥٦ كلمة ثالثة",
    "an_separators": "الإجمالي ٣\u066b١٤ و ١\u066c٢٣٤ ريال و ٥٠\u066a خصم",
    "an_latin_neighbors": "الملف report2026 رقم ٧ من ١٢ نسخة v2 بتاريخ ٢٠٢٦/١١/٢٣",
}

TEXT_GROUPS = {
    "text_core": (
        "short_arabic", "long_arabic", "mixed", "punct_edges",
        "diacritics", "lam_alef", "digits_mixed",
    ),
    "text_ordering": (
        "three_logical", "three_letters_rev", "three_fully_rev",
        "paren_number",
    ),
    "text_an": (
        "an_between_words", "an_separators", "an_latin_neighbors",
        "digits_mixed",
    ),
    "text_wrap": ("long_mixed",),
}
ENTRY_KEYS = ("mixed", "paren_number", "an_between_words")
TREE_KEYS = ("short_arabic", "mixed", "lam_alef", "three_logical", "paren_number", "an_separators")


def set_dpi_awareness():
    """Must run BEFORE tk.Tk(), or winfo_* and ImageGrab disagree on pixels."""
    if sys.platform != "win32":
        return "n/a"
    try:
        import ctypes

        hr = ctypes.windll.shcore.SetProcessDpiAwareness(2)  # per-monitor
        if hr == 0:
            return "per-monitor"
        return f"hresult={hr & 0xFFFFFFFF:#x}"  # 0x80070005 = already set
    except (AttributeError, OSError) as exc:
        try:
            ctypes.windll.user32.SetProcessDPIAware()
            return f"system ({type(exc).__name__} on shcore)"
        except Exception:
            return "unavailable"


def pixel_stats(img):
    g = img.convert("L")
    lo, hi = g.getextrema()
    hist = g.histogram()
    total = g.width * g.height
    return {"min": lo, "max": hi, "dark_ratio": round(sum(hist[:128]) / total, 5)}


def wait_viewable(widget, timeout=VIEWABLE_TIMEOUT):
    """Pump events until the widget is really mapped and has a real size."""
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        widget.update()
        if widget.winfo_viewable() and widget.winfo_width() > 1 and widget.winfo_height() > 1:
            return True
        time.sleep(0.05)
    return False


def settle(widget, rounds=10, delay=0.05):
    """Let the window manager paint after mapping."""
    for _ in range(rounds):
        widget.update()
        time.sleep(delay)


def main():
    import tkinter as tk
    from tkinter import ttk

    from PIL import ImageGrab

    os.makedirs(OUT, exist_ok=True)
    dpi_mode = set_dpi_awareness()

    try:
        root = tk.Tk()
    except tk.TclError as exc:
        print(f"PROBE_UNAVAILABLE: no display: {exc}", flush=True)
        return 0
    root.withdraw()  # every widget gets its own Toplevel; the root stays hidden

    screen_w, screen_h = root.winfo_screenwidth(), root.winfo_screenheight()
    report = {
        "platform": sys.platform,
        "tk": tk.TkVersion,
        "dpi_awareness": dpi_mode,
        "dpi_scale": round(root.winfo_fpixels("1i") / 72.0, 3),
        "screen": [screen_w, screen_h],
        "captures": [],
        "failures": [],
    }
    failures = report["failures"]

    with open(os.path.join(OUT, "fixtures.json"), "w", encoding="utf-8") as fh:
        json.dump(FIXTURES, fh, ensure_ascii=False, indent=1)

    # -- widget builders: each returns the widget, already packed -------------
    def text_builder(keys):
        def build(win):
            w = tk.Text(win, wrap=tk.WORD, font=FONT)
            for k in keys:
                w.insert(tk.END, f"[{k}]\n{FIXTURES[k]}\n\n")  # Latin label above each fixture
            w.pack(fill=tk.BOTH, expand=True)
            return w
        return build

    def entry_builder(key):
        def build(win):
            w = ttk.Entry(win, font=FONT)
            w.insert(0, FIXTURES[key])  # programmatic input, not real keyboard
            w.pack(fill=tk.X, padx=8, pady=8)
            return w
        return build

    def tree_builder(keys):
        def build(win):
            w = ttk.Treeview(win, columns=("v",), show="headings", height=len(keys))
            w.heading("v", text="value")
            w.column("v", width=max(200, win.winfo_screenwidth() // 2), stretch=True)
            for k in keys:
                w.insert("", "end", values=(FIXTURES[k],))
            w.pack(fill=tk.BOTH, expand=True)
            return w
        return build

    plan = [(name, 560, text_builder(keys)) for name, keys in TEXT_GROUPS.items()]
    plan += [(f"entry_{k}", 90, entry_builder(k)) for k in ENTRY_KEYS]
    plan.append(("treeview", 300, tree_builder(TREE_KEYS)))

    # -- capture loop: one Toplevel per widget, per width ---------------------
    for requested_w in WIDTHS:
        for name, height, build in plan:
            label = f"{name}_{requested_w}"
            win = tk.Toplevel(root)
            try:
                win.title(f"probe-{label}")
                w_px = min(requested_w, screen_w)
                h_px = min(height, max(100, screen_h - 80))
                win.geometry(f"{w_px}x{h_px}+0+0")
                win.attributes("-topmost", True)
                widget = build(win)

                if not wait_viewable(widget):
                    failures.append(f"{label}: widget never became viewable within {VIEWABLE_TIMEOUT}s")
                    print(f"FAIL {label}: not viewable", flush=True)
                    continue
                win.lift()
                try:
                    win.focus_force()
                except tk.TclError:
                    pass
                settle(win)

                x, y = widget.winfo_rootx(), widget.winfo_rooty()
                wd, ht = widget.winfo_width(), widget.winfo_height()
                bbox = (x, y, x + wd, y + ht)
                if x < 0 or y < 0 or bbox[2] > screen_w or bbox[3] > screen_h:
                    failures.append(f"{label}: bbox {bbox} exceeds screen {screen_w}x{screen_h}")
                    print(f"FAIL {label}: bbox off-screen {bbox}", flush=True)
                    continue

                img = ImageGrab.grab(bbox)
                path = os.path.join(OUT, f"{label}.png")
                img.save(path)
                stats = pixel_stats(img)
                entry = {
                    "file": path,
                    "requested_width": requested_w,
                    "actual_window_width": w_px,
                    "bbox": bbox,
                    **stats,
                }
                report["captures"].append(entry)
                print(f"captured {path} {stats}", flush=True)

                if stats["max"] == stats["min"]:
                    failures.append(f"{label}: uniform capture (min == max == {stats['min']})")
                    print(f"FAIL {label}: uniform pixels", flush=True)
                elif stats["max"] - stats["min"] < 8:
                    print(f"WARN {label}: very low contrast ({stats['min']}..{stats['max']})", flush=True)
            finally:
                win.destroy()
                root.update()

    root.destroy()
    with open(os.path.join(OUT, "metrics.json"), "w", encoding="utf-8") as fh:
        json.dump(report, fh, ensure_ascii=False, indent=1)

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
    except ImportError as exc:  # tkinter / Pillow missing: environment, not a render result
        print(f"PROBE_UNAVAILABLE: {type(exc).__name__}: {exc}", flush=True)
        sys.exit(0)
    except Exception:
        traceback.print_exc()
        print("PROBE_ERROR", flush=True)
        sys.exit(1)

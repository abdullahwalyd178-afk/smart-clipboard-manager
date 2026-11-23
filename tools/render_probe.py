"""Windows-render probe: draw real Tk widgets with Arabic/BiDi fixtures and
capture actual pixels via PIL.ImageGrab, uploaded as a CI artifact.

Purpose: judge whether the OS text stack (Uniscribe/DirectWrite) shapes and
reorders Arabic correctly in Tk 8.6 on Windows - joining, paragraph direction,
digits, wrap behaviour. Input insertion here is PROGRAMMATIC (widget.insert /
event_generate); it is not real-keyboard coverage and is not claimed as such.
"""
import json
import os
import sys
import time

OUT = "render-out"
os.makedirs(OUT, exist_ok=True)

FIXTURES = {
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
}


def black_stats(img):
    g = img.convert("L")
    lo, hi = g.getextrema()
    return {"min": lo, "max": hi}


def main():
    import tkinter as tk
    from tkinter import ttk

    from PIL import ImageGrab

    report = {"platform": sys.platform, "tk": tk.TkVersion, "captures": []}
    root = tk.Tk()
    root.title("render-probe")

    for width in (640, 1024):
        for child in root.winfo_children():
            child.destroy()
        root.geometry(f"{width}x560+40+40")
        nb = ttk.Notebook(root)
        nb.pack(fill=tk.BOTH, expand=True)
        text = tk.Text(nb, wrap=tk.WORD, font=("Segoe UI", 11))
        text.insert("1.0", "\n\n".join(FIXTURES[k] for k in (
            "short_arabic", "long_arabic", "mixed", "punct_edges",
            "diacritics", "lam_alef", "digits_mixed")))
        nb.add(text, text="Text")
        entry = ttk.Entry(nb, font=("Segoe UI", 11))
        entry.insert(0, FIXTURES["mixed"])  # programmatic input, not real keyboard
        nb.add(entry, text="Entry")
        tree = ttk.Treeview(nb, columns=("v",), show="headings")
        tree.heading("v", text="value")
        for k in ("short_arabic", "mixed", "lam_alef"):
            tree.insert("", "end", values=(FIXTURES[k],))
        nb.add(tree, text="Treeview")
        root.update_idletasks()
        root.update()
        time.sleep(1.0)  # let the WM actually paint
        for name, w in (("text", text), ("entry", entry), ("treeview", tree)):
            x, y = w.winfo_rootx(), w.winfo_rooty()
            bbox = (x, y, x + w.winfo_width(), y + w.winfo_height())
            img = ImageGrab.grab(bbox)
            path = os.path.join(OUT, f"{name}_{width}.png")
            img.save(path)
            stats = black_stats(img)
            report["captures"].append({"file": path, "bbox": bbox, **stats})
            print(f"captured {path} extrema={stats}", flush=True)
    root.update()
    root.destroy()
    with open(os.path.join(OUT, "metrics.json"), "w", encoding="utf-8") as fh:
        json.dump(report, fh, ensure_ascii=False, indent=1)
    blanks = [c["file"] for c in report["captures"] if c["max"] - c["min"] < 8]
    if blanks:
        print("WARNING: captures look blank/uniform (session may be non-visible): " + ", ".join(blanks), flush=True)
    print("PROBE_DONE", flush=True)
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as exc:  # report, keep job green so the limit is visible
        print(f"PROBE_UNAVAILABLE: {type(exc).__name__}: {exc}", flush=True)
        sys.exit(0)

"""Standalone history window (Tkinter, stdlib only).

This is the app's real UI beyond the tray menu: full history, instant search,
kind/favorite filters, pin/favorite/tags/delete/copy-back, and OCR retry for
image items. It is also the quick-search window: opened standalone
(``python -m clipboard_manager ui``), from the tray ("Open history window"),
or by the global hotkey - so anything you copied is one search away without
leaving the app you are working in. Selecting an item and pressing Enter (or
the Copy back button) puts it on the clipboard, ready to paste.

Tkinter ships with python.org Windows builds, so there is no extra dependency.
"""

from __future__ import annotations

import logging
import tkinter as tk
from tkinter import messagebox, simpledialog, ttk

from .models import IMAGE, TEXT
from .storage import ClipboardStore
from .text_shaping import base_is_rtl, shape_for_display
from .watcher import ClipboardProvider

logger = logging.getLogger(__name__)

FILTERS = ("All", "Text", "Images", "Favorites")


def _display_text(text: str) -> str:
    """Prepare text for Tk display.

    Tk does no Arabic shaping or bidi layout: raw Arabic strings render
    left-to-right with disconnected glyphs. When the optional
    ``arabic_reshaper`` + ``python-bidi`` packages are installed, Arabic text
    is pre-shaped and visually reordered so it displays correctly on every
    platform. Without them the text is returned unchanged (still usable, just
    not shaped).
    """
    if not any("\u0600" <= ch <= "\u06FF" for ch in text):
        return text
    try:
        import arabic_reshaper  # type: ignore
        from bidi.algorithm import get_display  # type: ignore
    except ImportError:
        return text
    return get_display(arabic_reshaper.reshape(text))


class HistoryWindow:
    def __init__(
        self,
        store: ClipboardStore,
        provider: ClipboardProvider | None,
        config=None,
        root: tk.Tk | None = None,
    ):
        self.store = store
        self.provider = provider
        self.config = config
        self._owns_root = root is None
        self.root = root or tk.Tk()
        self.root.title("Smart Clipboard - History")
        self.root.geometry("900x480")
        self.root.bind("<Escape>", lambda _e: self.close())

        top = ttk.Frame(self.root, padding=6)
        top.pack(fill=tk.X)
        ttk.Label(top, text="Search:").pack(side=tk.LEFT)
        # search_var always holds the LOGICAL text (used for filtering);
        # the entry widget only shows the shaped display copy.
        self.search_var = tk.StringVar()
        self._search_display_var = tk.StringVar()
        entry = ttk.Entry(top, textvariable=self._search_display_var, width=32)
        entry.pack(side=tk.LEFT, padx=(4, 10))
        self._search_entry = entry
        self._bind_shaped_input(entry)
        entry.bind("<KeyRelease>", lambda _e: self.refresh())
        self.filter_var = tk.StringVar(value=FILTERS[0])
        combo = ttk.Combobox(
            top, textvariable=self.filter_var, values=FILTERS, width=10, state="readonly"
        )
        combo.pack(side=tk.LEFT)
        combo.bind("<<ComboboxSelected>>", lambda _e: self.refresh())
        self.status_var = tk.StringVar()
        ttk.Label(top, textvariable=self.status_var).pack(side=tk.RIGHT)

        columns = ("kind", "marks", "preview", "tags", "created")
        self.tree = ttk.Treeview(self.root, columns=columns, show="headings", selectmode="browse")
        self.tree.heading("kind", text="Kind")
        self.tree.heading("marks", text="★/•")
        self.tree.heading("preview", text="Content")
        self.tree.heading("tags", text="Tags")
        self.tree.heading("created", text="Copied at (UTC)")
        self.tree.column("kind", width=55, anchor=tk.W)
        self.tree.column("marks", width=50, anchor=tk.CENTER)
        self.tree.column("preview", width=360, anchor=tk.W)
        self.tree.column("tags", width=120, anchor=tk.W)
        self.tree.column("created", width=170, anchor=tk.W)
        self.tree.pack(fill=tk.BOTH, expand=True, padx=6)
        self.tree.bind("<Return>", lambda _e: self.copy_back())
        self.tree.bind("<Double-1>", lambda _e: self.copy_back())
        self.tree.bind("<F2>", lambda _e: self.view_full())

        buttons = ttk.Frame(self.root, padding=6)
        buttons.pack(fill=tk.X)
        ttk.Button(buttons, text="Copy back (Enter)", command=self.copy_back).pack(side=tk.LEFT)
        ttk.Button(buttons, text="View full (F2)", command=self.view_full).pack(side=tk.LEFT, padx=4)
        ttk.Button(buttons, text="Pin/Unpin", command=self.toggle_pin).pack(side=tk.LEFT, padx=4)
        ttk.Button(buttons, text="Favorite", command=self.toggle_favorite).pack(side=tk.LEFT)
        ttk.Button(buttons, text="Edit tags", command=self.edit_tags).pack(side=tk.LEFT, padx=4)
        ttk.Button(buttons, text="Retry OCR", command=self.retry_ocr).pack(side=tk.LEFT)
        ttk.Button(buttons, text="Delete", command=self.delete).pack(side=tk.LEFT, padx=4)
        ttk.Button(buttons, text="Close (Esc)", command=self.close).pack(side=tk.RIGHT)

        entry.focus_set()
        self.refresh()

    # -- shaped search input -------------------------------------------------
    #
    # Tk on X11 draws Entry text without bidi reordering, so Arabic typed
    # into a plain Entry appears reversed. The entry below is display-only:
    # every edit is intercepted, the LOGICAL text lives in self.search_var,
    # and the widget shows shape_for_display(logical). Cursor is pinned to
    # the visual end of the text (start for RTL, end for LTR).

    def _bind_shaped_input(self, entry: ttk.Entry) -> None:
        entry.bind("<Key>", self._on_search_key)
        entry.bind("<<Paste>>", self._on_search_paste)

    def _on_search_key(self, event: tk.Event) -> str | None:
        if event.state & 0x4:  # Ctrl combos (copy/all/...) keep default behavior
            return None
        text = self.search_var.get()
        if event.keysym == "BackSpace":
            text = text[:-1]
        elif event.keysym == "Delete":
            text = ""
        elif event.char and event.char.isprintable():
            text += event.char
        else:
            return None  # arrows, Tab, F-keys: default behavior
        self._set_search_text(text)
        return "break"

    def _on_search_paste(self, _event: tk.Event) -> str:
        try:
            text = self.search_var.get() + self.root.clipboard_get()
        except tk.TclError:
            text = self.search_var.get()
        self._set_search_text(text)
        return "break"

    def _set_search_text(self, text: str) -> None:
        self.search_var.set(text)
        display = shape_for_display(text)
        self._search_display_var.set(display)
        if display:
            self._search_entry.icursor(0 if base_is_rtl(text) else tk.END)
        self.refresh()

    # -- full-content viewer --------------------------------------------------

    def view_full(self) -> None:
        item_id = self._selected_id()
        if item_id is None:
            return
        item = self.store.get(item_id)
        if item is None:
            return
        body = item.text or item.ocr_text or ""
        if not body and item.image_path:
            body = f"[image: {item.image_path}]"
        win = tk.Toplevel(self.root)
        win.title("Full content")
        # Place near the main window, clamped to the screen so the viewer
        # never opens off the visible area.
        self.root.update_idletasks()
        x = max(0, min(self.root.winfo_x() + 40, win.winfo_screenwidth() - 640))
        y = max(0, min(self.root.winfo_y() + 40, win.winfo_screenheight() - 400))
        win.geometry(f"640x400+{x}+{y}")
        meta = f"{item.kind} - copied {item.created_at}"
        if item.tags:
            meta += " - tags: " + item.tags.replace(",", ", ")
        ttk.Label(win, text=meta).pack(anchor=tk.W, padx=8, pady=(8, 0))
        # Read-only Text (not Message) so long content scrolls and the user
        # can select and copy it. Keys are swallowed to keep it read-only;
        # Ctrl combos (copy) keep their default behavior.
        ttk.Button(win, text="Close (Esc)", command=win.destroy).pack(side=tk.BOTTOM, pady=(0, 8))
        frame = ttk.Frame(win)
        frame.pack(fill=tk.BOTH, expand=True, padx=8, pady=8)
        text = tk.Text(frame, wrap=tk.WORD, width=72, height=20)
        scroll = ttk.Scrollbar(frame, orient=tk.VERTICAL, command=text.yview)
        text.configure(yscrollcommand=scroll.set)
        text.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        scroll.pack(side=tk.RIGHT, fill=tk.Y)
        text.insert("1.0", shape_for_display(body))
        text.bind("<Key>", lambda e: None if (e.state & 0x4 or e.keysym == "Escape") else "break")
        win.bind("<Escape>", lambda _e: win.destroy())
        text.focus_set()

    # -- data ---------------------------------------------------------------

    def _query(self) -> tuple[str, str | None, bool]:
        text = self.search_var.get().strip()
        selected = self.filter_var.get()
        kind = {"Text": TEXT, "Images": IMAGE}.get(selected)
        return text, kind, selected == "Favorites"

    def refresh(self) -> None:
        text, kind, favorites = self._query()
        items = self.store.search(text, kind=kind, favorites_only=favorites, limit=300)
        # Preserve the selection across the rebuild so chained actions
        # (pin, then favorite, then delete) keep acting on the same item.
        selected = self._selected_id()
        self.tree.delete(*self.tree.get_children())
        for item in items:
            marks = ("•" if item.pinned else "") + ("★" if item.favorite else "")
            preview = _display_text(item.preview(90))
            if item.kind == IMAGE and item.ocr_status == "failed":
                preview = "[OCR failed - Retry OCR] " + preview
            self.tree.insert(
                "",
                tk.END,
                iid=str(item.id),
                values=(item.kind, marks, preview, item.tags.replace(",", ", "), item.created_at[:16].replace("T", " ")),
            )
        self.status_var.set(f"{len(items)} item(s)")
        if selected is not None and self.tree.exists(str(selected)):
            self.tree.selection_set(str(selected))

    def _selected_id(self) -> int | None:
        selection = self.tree.selection()
        return int(selection[0]) if selection else None

    # -- actions --------------------------------------------------------------

    def copy_back(self) -> None:
        item_id = self._selected_id()
        if item_id is None or self.provider is None:
            return
        item = self.store.get(item_id)
        value = item and (item.text or item.ocr_text)
        if not value:
            self.status_var.set("nothing to copy (image without OCR text)")
            return
        try:
            self.provider.set_text(value)
            self.status_var.set("copied - paste with Ctrl+V")
        except Exception:
            logger.exception("copy back failed")
            self.status_var.set("copy failed")

    def toggle_pin(self) -> None:
        item_id = self._selected_id()
        if item_id is None:
            return
        item = self.store.get(item_id)
        if item:
            self.store.set_pinned(item_id, not item.pinned)
            self.refresh()

    def toggle_favorite(self) -> None:
        item_id = self._selected_id()
        if item_id is None:
            return
        item = self.store.get(item_id)
        if item:
            self.store.set_favorite(item_id, not item.favorite)
            self.refresh()

    def edit_tags(self) -> None:
        item_id = self._selected_id()
        if item_id is None:
            return
        item = self.store.get(item_id)
        if not item:
            return
        current = ", ".join(item.tag_list())
        answer = simpledialog.askstring(
            "Tags", "Comma-separated tags:", initialvalue=current, parent=self.root
        )
        if answer is not None:
            self.store.set_tags(item_id, answer)
            self.refresh()

    def retry_ocr(self) -> None:
        item_id = self._selected_id()
        if item_id is None or self.config is None:
            self.status_var.set("OCR retry needs the app configuration")
            return
        from .ocr import retry_ocr

        try:
            text = retry_ocr(self.store, self.config, item_id)
        except Exception as exc:
            messagebox.showerror("OCR retry failed", str(exc), parent=self.root)
            self.refresh()
            return
        self.status_var.set("OCR done" if text.strip() else "OCR found no text")
        self.refresh()

    def delete(self) -> None:
        item_id = self._selected_id()
        if item_id is None:
            return
        removed = self.store.delete(item_id)
        if removed and removed.image_path:
            from pathlib import Path

            try:
                Path(removed.image_path).unlink(missing_ok=True)
            except OSError:
                pass
        self.refresh()

    def close(self) -> None:
        self.root.destroy()

    def run(self) -> None:
        self.root.mainloop()


def open_history_window(
    store: ClipboardStore,
    provider: ClipboardProvider | None = None,
    config=None,
) -> None:
    """Open the standalone history window (blocks until closed)."""
    HistoryWindow(store, provider, config).run()

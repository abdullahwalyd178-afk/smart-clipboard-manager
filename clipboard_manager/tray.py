"""System tray UI (pystray).

Menu:
- Pause / Resume capture (privacy switch - while paused nothing is recorded)
- Recent items: each entry has Copy / Pin-Unpin / Delete
- Clear unpinned (pinned items are kept)
- Quit
"""

from __future__ import annotations

import pystray
from PIL import Image, ImageDraw

from .models import IMAGE, TEXT, ClipboardItem
from .storage import ClipboardStore
from .watcher import ClipboardWatcher, ClipboardProvider


def build_icon_image(size: int = 64) -> Image.Image:
    """Simple clipboard-glyph icon drawn with PIL (no asset files needed)."""
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    m = size // 8
    # board
    d.rounded_rectangle([m, m + 4, size - m, size - m], radius=6, fill=(33, 150, 243, 255))
    # clip
    d.rounded_rectangle(
        [size // 2 - size // 6, m - 2, size // 2 + size // 6, m + 10], radius=4, fill=(21, 101, 192, 255)
    )
    # text lines
    line_x0, line_x1 = m + 8, size - m - 8
    for i in range(3):
        y = m + 16 + i * (size // 6)
        d.line([line_x0, y, line_x1 - (12 if i == 2 else 0), y], fill=(255, 255, 255, 255), width=3)
    return img


class TrayApp:
    def __init__(
        self,
        store: ClipboardStore,
        watcher: ClipboardWatcher,
        provider: ClipboardProvider,
        on_quit=None,
    ):
        self.store = store
        self.watcher = watcher
        self.provider = provider
        self.on_quit = on_quit
        self.icon = pystray.Icon(
            "smart-clipboard",
            build_icon_image(),
            "Smart Clipboard",
            menu=pystray.Menu(
                pystray.MenuItem("Open history window", self._open_window, default=True),
                pystray.MenuItem(
                    lambda item: "Resume capture" if self.watcher.paused else "Pause capture",
                    self._toggle_pause,
                ),
                pystray.MenuItem("Recent", pystray.Menu(self._recent_menu)),
                pystray.MenuItem("Clear unpinned", self._clear_unpinned),
                pystray.Menu.SEPARATOR,
                pystray.MenuItem("Quit", self._quit),
            ),
        )

    # -- menu actions ------------------------------------------------------

    def _open_window(self, icon=None, item=None) -> None:
        import subprocess
        import sys

        subprocess.Popen(
            [sys.executable, "-m", "clipboard_manager", "ui"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )

    def _toggle_pause(self, icon=None, item=None) -> None:
        if self.watcher.paused:
            self.watcher.resume()
        else:
            self.watcher.pause()
        self.icon.update_menu()

    def _recent_menu(self):
        items = self.store.list_items(10)
        if not items:
            return [pystray.MenuItem("(empty)", None, enabled=False)]
        return [self._item_submenu(it) for it in items]

    def _item_submenu(self, item: ClipboardItem) -> pystray.MenuItem:
        copyable = item.text or item.ocr_text
        return pystray.MenuItem(
            item.preview(),
            pystray.Menu(
                pystray.MenuItem(
                    "Copy back",
                    self._make_copy(item),
                    enabled=bool(copyable),
                    default=True,
                ),
                pystray.MenuItem(
                    "Unpin" if item.pinned else "Pin (keep forever)",
                    self._make_pin(item),
                ),
                pystray.MenuItem("Delete", self._make_delete(item)),
            ),
        )

    def _make_copy(self, item: ClipboardItem):
        def action(icon=None, menu_item=None) -> None:
            value = item.text or item.ocr_text
            if value:
                try:
                    self.provider.set_text(value)
                except Exception:
                    pass

        return action

    def _make_pin(self, item: ClipboardItem):
        def action(icon=None, menu_item=None) -> None:
            self.store.set_pinned(item.id, not item.pinned)
            item.pinned = not item.pinned
            self.icon.update_menu()

        return action

    def _make_delete(self, item: ClipboardItem):
        def action(icon=None, menu_item=None) -> None:
            removed = self.store.delete(item.id)
            if removed and removed.image_path:
                from pathlib import Path
                try:
                    Path(removed.image_path).unlink(missing_ok=True)
                except OSError:
                    pass
            self.icon.update_menu()

        return action

    def _clear_unpinned(self, icon=None, item=None) -> None:
        removed = self.store.clear_unpinned()
        for clip in removed:
            if clip.image_path:
                from pathlib import Path
                try:
                    Path(clip.image_path).unlink(missing_ok=True)
                except OSError:
                    pass
        self.icon.update_menu()

    def _quit(self, icon=None, item=None) -> None:
        self.watcher.stop()
        if self.on_quit:
            self.on_quit()
        self.icon.stop()

    # -- run ---------------------------------------------------------------

    def run(self) -> None:
        self.watcher.start()
        self.icon.run()

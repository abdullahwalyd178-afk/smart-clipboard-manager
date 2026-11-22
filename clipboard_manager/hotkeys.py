"""Global hotkey for the quick-search window (Windows).

Uses the Win32 ``RegisterHotKey`` API directly through ctypes - no third-party
dependency. A background thread owns a hidden message loop; when the hotkey
fires the callback runs on that thread, so the callback should hand real work
to the UI (e.g. via ``after``) instead of doing it inline.

Honest scope: global hotkeys are only implemented on Windows. On other
platforms ``HotkeyManager.available()`` is False and ``start`` is a no-op
with a log line - nothing pretends to work.
"""

from __future__ import annotations

import logging
import sys
import threading

logger = logging.getLogger(__name__)

_MODIFIERS = {
    "ctrl": 0x0002,  # MOD_CONTROL
    "control": 0x0002,
    "alt": 0x0001,  # MOD_ALT
    "shift": 0x0004,  # MOD_SHIFT
    "win": 0x0008,  # MOD_WIN
}

_VK = {chr(c).lower(): c for c in range(ord("A"), ord("Z") + 1)}
_VK.update({str(d): ord(str(d)) for d in range(10)})
_VK.update({f"f{i}": 0x6F + i for i in range(1, 13)})
_VK.update({"space": 0x20, "tab": 0x09, "escape": 0x1B, "insert": 0x2D, "delete": 0x2E})


def parse_hotkey(spec: str) -> tuple[int, int]:
    """Parse "ctrl+shift+v" into (modifier_mask, virtual_key). Raises ValueError."""
    parts = [p.strip().lower() for p in (spec or "").split("+") if p.strip()]
    if len(parts) < 2:
        raise ValueError(f"hotkey {spec!r} needs a modifier and a key, e.g. 'ctrl+shift+v'")
    modifiers = 0
    key = None
    for part in parts:
        if part in _MODIFIERS:
            modifiers |= _MODIFIERS[part]
        elif part in _VK and key is None:
            key = _VK[part]
        else:
            raise ValueError(f"unknown key in hotkey {spec!r}: {part!r}")
    if not modifiers or key is None:
        raise ValueError(f"hotkey {spec!r} needs at least one modifier and one key")
    return modifiers, key


class HotkeyManager:
    """Register one global hotkey and invoke a callback when it is pressed."""

    _HOTKEY_ID = 1

    def __init__(self, spec: str, callback):
        self.spec = spec
        self.callback = callback
        self._thread: threading.Thread | None = None
        self._thread_id: int | None = None
        self._registered = threading.Event()
        self._failed: BaseException | None = None

    @staticmethod
    def available() -> bool:
        return sys.platform == "win32"

    def start(self) -> bool:
        """Start listening. Returns False (with a log) when unavailable."""
        if not self.available():
            logger.info("global hotkey %r not registered: only supported on Windows", self.spec)
            return False
        if self._thread is not None:
            return True
        self._thread = threading.Thread(
            target=self._run, name="global-hotkey", daemon=True
        )
        self._thread.start()
        # Wait briefly so a registration error surfaces to the caller.
        if self._registered.wait(timeout=5) and self._failed is not None:
            logger.warning("could not register hotkey %r: %s", self.spec, self._failed)
            return False
        return True

    def stop(self) -> None:
        if not self.available() or self._thread is None:
            return
        import ctypes

        ctypes.windll.user32.PostThreadMessageW(self._thread_id, 0x0012, 0, 0)  # WM_QUIT
        self._thread.join(timeout=5)
        self._thread = None

    def _run(self) -> None:
        import ctypes
        from ctypes import wintypes

        user32 = ctypes.windll.user32
        self._thread_id = threading.get_native_id()
        try:
            modifiers, vk = parse_hotkey(self.spec)
            if not user32.RegisterHotKey(None, self._HOTKEY_ID, modifiers, vk):
                self._failed = OSError(
                    "RegisterHotKey failed (another app may already use this shortcut)"
                )
                self._registered.set()
                return
            self._registered.set()
            msg = wintypes.MSG()
            while user32.GetMessageW(ctypes.byref(msg), None, 0, 0) > 0:
                if msg.message == 0x0312:  # WM_HOTKEY
                    try:
                        self.callback()
                    except Exception:
                        logger.exception("hotkey callback failed")
        except Exception as exc:  # registration errors surface via start()
            self._failed = exc
            self._registered.set()
        finally:
            user32.UnregisterHotKey(None, self._HOTKEY_ID)

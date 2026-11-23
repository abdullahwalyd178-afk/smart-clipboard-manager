"""Windows smoke tests: real platform APIs exercised on the windows CI runner.

These SKIP on non-Windows. They prove the Windows-facing code paths execute
against the real OS (clipboard, user32 foreground query, RegisterHotKey,
locked-file semantics) - they do not prove interactive tray/hotkey UX, which
still needs a human at a real Windows desktop.
"""

import os
import sys
import time

import pytest

pytestmark = pytest.mark.skipif(sys.platform != "win32", reason="Windows-only smoke tests")


def test_real_clipboard_text_roundtrip():
    from clipboard_manager.clipboard import PyperclipPILProvider

    provider = PyperclipPILProvider()
    payload = "smart-clipboard win32 smoke \u0645\u0631\u062d\u0628\u0627"
    provider.set_text(payload)
    assert provider.get_text() == payload


def test_active_window_info_queries_real_user32():
    from clipboard_manager.sensitive import active_window_info

    result = active_window_info()  # real GetForegroundWindow/psapi path
    assert result is None or (
        isinstance(result, tuple) and len(result) == 2 and all(isinstance(x, str) for x in result)
    )


def test_hotkey_registration_attempt_is_clean():
    from clipboard_manager.hotkeys import GlobalHotkey

    fired = []
    hk = GlobalHotkey("ctrl+shift+f9", lambda: fired.append(1))
    started = hk.start()  # True = RegisterHotKey actually succeeded on this Windows
    assert hk.stop() is None  # clean teardown either way
    # No assertion on `started`: session-0 runners may refuse registration;
    # either outcome must be graceful, never a crash.
    assert isinstance(started, bool)


def test_sweep_survives_locked_orphan_file(store, images_dir):
    from clipboard_manager.maintenance import sweep_orphan_images

    locked = images_dir / "locked0.png"
    locked.write_bytes(b"png")
    old = time.time() - 120
    os.utime(locked, (old, old))
    with open(locked, "rb"):  # Windows refuses to delete an open file
        removed = sweep_orphan_images(store, images_dir, min_age_seconds=60)
    assert removed == []  # unlink failed gracefully, not reported as removed
    assert locked.exists()
    locked.unlink()


def test_config_dir_uses_appdata():
    from clipboard_manager.config import Config

    assert "SmartClipboard" in str(Config.config_path())

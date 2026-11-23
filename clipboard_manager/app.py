"""Application entry point and CLI.

Usage:
    python -m clipboard_manager            # run the tray app
    python -m clipboard_manager run --no-tray   # headless capture loop
    python -m clipboard_manager history    # print recent history
    python -m clipboard_manager clear      # delete all unpinned items
"""

from __future__ import annotations

import argparse
import sys
import threading
import time
from pathlib import Path

from .config import Config
from .maintenance import sweep_orphan_images
from .ocr import TrackingEngine, create_engine
from .sensitive import SensitiveFilterProvider
from .storage import ClipboardStore
from .watcher import ClipboardWatcher, PyperclipPILProvider

PURGE_INTERVAL_SECONDS = 3600  # re-apply the retention rule hourly while running


def _remove_image_files(items) -> None:
    for item in items:
        if item.image_path:
            try:
                Path(item.image_path).unlink(missing_ok=True)
            except OSError:
                pass


def _purge_loop(store: ClipboardStore, config: Config, stop: threading.Event) -> None:
    while not stop.wait(PURGE_INTERVAL_SECONDS):
        try:
            _remove_image_files(store.purge_expired(config.retention_days))
            _remove_image_files(store.enforce_max_items(config.max_items))
        except Exception as exc:
            print(f"[smart-clipboard] retention cleanup failed: {exc}", file=sys.stderr)


def _build_engine(config: Config):
    try:
        return create_engine(config)
    except Exception as exc:
        print(f"[smart-clipboard] OCR disabled: {exc}", file=sys.stderr)
        return None


def cmd_run(args) -> int:
    config = Config.load()
    Path(config.images_dir).mkdir(parents=True, exist_ok=True)
    store = ClipboardStore(config.db_path)

    # Apply the retention rule on startup, so old items disappear even if the
    # app was not running when they aged out. Also drop image files that no
    # database row references anymore (interrupted captures, old deletes).
    _remove_image_files(store.purge_expired(config.retention_days))
    _remove_image_files(store.enforce_max_items(config.max_items))
    sweep_orphan_images(store, config.images_dir)

    engine = _build_engine(config)
    if engine is not None:
        engine = TrackingEngine(engine, store)
    provider = PyperclipPILProvider()
    provider = SensitiveFilterProvider(
        provider,
        excluded_apps=list(config.excluded_apps),
        excluded_window_keywords=list(config.excluded_window_keywords),
        skip_suspected_secrets=config.skip_suspected_secrets,
    )
    watcher = ClipboardWatcher(
        store,
        provider,
        config.images_dir,
        ocr_engine=engine,
        poll_interval=config.poll_interval_seconds,
        copy_ocr_result_to_clipboard=config.copy_ocr_result_to_clipboard,
    )

    stop = threading.Event()
    purge_thread = threading.Thread(
        target=_purge_loop, args=(store, config, stop), name="retention-purge", daemon=True
    )
    purge_thread.start()

    hotkeys = None
    if not args.no_tray and config.quick_search_hotkey:
        from .hotkeys import HotkeyManager

        hotkeys = HotkeyManager(config.quick_search_hotkey, _open_ui_subprocess)
        hotkeys.start()

    try:
        if args.no_tray:
            print("[smart-clipboard] running headless (Ctrl+C to stop)")
            watcher.start()
            while True:
                time.sleep(1)
        else:
            from .tray import TrayApp

            TrayApp(store, watcher, provider).run()
    except KeyboardInterrupt:
        pass
    finally:
        stop.set()
        if hotkeys is not None:
            hotkeys.stop()
        watcher.stop()
        purge_thread.join(timeout=5)
        store.close()
    return 0


def _open_ui_subprocess() -> None:
    """Open the history window as its own process (Tk needs its own loop)."""
    import subprocess

    subprocess.Popen(
        [sys.executable, "-m", "clipboard_manager", "ui"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )


def cmd_ui(args) -> int:
    config = Config.load()
    Path(config.images_dir).mkdir(parents=True, exist_ok=True)
    from .ui_launch import claim_ui_instance, release_ui_instance

    if not claim_ui_instance(config.data_dir):
        print("[smart-clipboard] history window is already open")
        return 0
    store = ClipboardStore(config.db_path)
    try:
        from .ui import open_history_window

        open_history_window(store, PyperclipPILProvider(), config)
    finally:
        release_ui_instance(config.data_dir)
        store.close()
    return 0


def cmd_history(args) -> int:
    config = Config.load()
    with ClipboardStore(config.db_path) as store:
        items = store.list_items(args.limit)
    if not items:
        print("(history is empty)")
        return 0
    for item in items:
        print(f"#{item.id} [{item.kind}] {item.created_at}  {item.preview()}")
    return 0


def cmd_clear(args) -> int:
    config = Config.load()
    with ClipboardStore(config.db_path) as store:
        removed = store.clear_unpinned()
    _remove_image_files(removed)
    print(f"removed {len(removed)} unpinned item(s); pinned items kept")
    return 0


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="smart-clipboard")
    sub = parser.add_subparsers(dest="command")

    p_run = sub.add_parser("run", help="run the tray app (default)")
    p_run.add_argument("--no-tray", action="store_true", help="run without the tray icon")
    p_run.set_defaults(func=cmd_run)

    p_hist = sub.add_parser("history", help="print recent history")
    p_hist.add_argument("--limit", type=int, default=20)
    p_hist.set_defaults(func=cmd_history)

    p_clear = sub.add_parser("clear", help="delete all unpinned items")
    p_clear.set_defaults(func=cmd_clear)

    p_ui = sub.add_parser("ui", help="open the standalone history window")
    p_ui.set_defaults(func=cmd_ui)

    args = parser.parse_args(argv)
    if not hasattr(args, "func"):
        args = parser.parse_args(["run"] + (argv or []))
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())

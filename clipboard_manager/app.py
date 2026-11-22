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
from .ocr import create_engine
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
        _remove_image_files(store.purge_expired(config.retention_days))
        _remove_image_files(store.enforce_max_items(config.max_items))


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
    # app was not running when they aged out.
    _remove_image_files(store.purge_expired(config.retention_days))

    engine = _build_engine(config)
    provider = PyperclipPILProvider()
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
        watcher.stop()
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

    args = parser.parse_args(argv)
    if not hasattr(args, "func"):
        args = parser.parse_args(["run"] + (argv or []))
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())

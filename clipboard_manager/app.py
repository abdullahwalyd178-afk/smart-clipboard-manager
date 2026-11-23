"""Application entry point and CLI.

Usage:
    python -m clipboard_manager            # run the tray app
    python -m clipboard_manager run --no-tray   # headless capture loop
    python -m clipboard_manager history    # print recent history
    python -m clipboard_manager clear      # delete all unpinned items
"""

from __future__ import annotations

import argparse
import logging
import sys
import threading
import time
from pathlib import Path

from .config import Config
from .ocr import create_engine
from .storage import ClipboardStore
from .image_cleanup import clear_unpinned, purge_and_enforce
from .watcher import ClipboardWatcher, PyperclipPILProvider

logger = logging.getLogger(__name__)

PURGE_INTERVAL_SECONDS = 3600  # re-apply the retention rule hourly while running


def _purge_loop(store: ClipboardStore, config: Config, stop: threading.Event) -> None:
    while not stop.wait(PURGE_INTERVAL_SECONDS):
        try:
            purge_and_enforce(
                store, config.images_dir, config.retention_days, config.max_items
            )
        except Exception:
            logger.exception("Retention cleanup failed")


def _build_engine(config: Config):
    try:
        return create_engine(config)
    except Exception as exc:
        logger.warning("OCR disabled: %s", exc)
        return None


def cmd_run(args) -> int:
    config = Config.load()
    Path(config.images_dir).mkdir(parents=True, exist_ok=True)
    store = ClipboardStore(config.db_path)

    # Apply retention under the same cross-process lock as image capture.
    purge_and_enforce(
        store, config.images_dir, config.retention_days, config.max_items
    )

    engine = _build_engine(config)
    provider = PyperclipPILProvider()
    watcher = ClipboardWatcher(
        store,
        provider,
        config.images_dir,
        ocr_engine=engine,
        poll_interval=config.poll_interval_seconds,
        copy_ocr_result_to_clipboard=config.copy_ocr_result_to_clipboard,
        max_items=config.max_items,
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
        watcher_stopped = watcher.stop()
        purge_thread.join(timeout=5)
        if watcher_stopped:
            store.close()
        else:
            logger.warning(
                "Watcher is still busy; leaving the database open until process exit"
            )
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
        removed = clear_unpinned(store, config.images_dir)
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

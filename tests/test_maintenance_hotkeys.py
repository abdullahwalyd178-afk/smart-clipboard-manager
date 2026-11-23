"""Orphan-image sweep and hotkey parsing."""

import pytest

from clipboard_manager.hotkeys import parse_hotkey
from clipboard_manager.maintenance import sweep_orphan_images


def test_orphan_images_removed_referenced_kept(store, images_dir):
    referenced = images_dir / "abc123.png"
    referenced.write_bytes(b"png")
    orphan = images_dir / "dead99.png"
    orphan.write_bytes(b"png")
    not_an_image = images_dir / "notes.txt"
    not_an_image.write_text("leave me")

    store.add_image(str(referenced), digest="f" * 64)

    removed = sweep_orphan_images(store, images_dir)
    assert removed == [orphan]
    assert referenced.exists()
    assert not orphan.exists()
    assert not_an_image.exists()  # only .png files are candidates


def test_sweep_with_missing_directory(store, tmp_path):
    assert sweep_orphan_images(store, tmp_path / "nope") == []


def test_parse_hotkey_combinations():
    mods, vk = parse_hotkey("ctrl+shift+v")
    assert mods == 0x0002 | 0x0004 and vk == ord("V")
    mods, vk = parse_hotkey("WIN + F9")
    assert mods == 0x0008 and vk == 0x78


def test_parse_hotkey_rejects_bad_specs():
    for bad in ("", "v", "ctrl+", "ctrl+banana", "shift+ctrl"):
        with pytest.raises(ValueError):
            parse_hotkey(bad)


def test_periodic_sweep_keeps_fresh_orphan_removes_aged(store, images_dir):
    # Race guard: a capture writes the PNG before its database row exists, so
    # a periodic sweep must not delete files written moments ago.
    fresh = images_dir / "fresh00.png"
    fresh.write_bytes(b"png")
    aged = images_dir / "aged000.png"
    aged.write_bytes(b"png")

    removed = sweep_orphan_images(store, images_dir, min_age_seconds=60)
    assert removed == []
    assert fresh.exists() and aged.exists()

    # Backdate the aged file beyond the grace window; only it is swept.
    import os
    import time

    old = time.time() - 120
    os.utime(aged, (old, old))
    removed = sweep_orphan_images(store, images_dir, min_age_seconds=60)
    assert removed == [aged]
    assert fresh.exists()  # still within grace, checked again next sweep
    assert not aged.exists()

    # A fresh file whose row exists is never touched, whatever its age.
    store.add_image(str(fresh), digest="e" * 64)
    removed = sweep_orphan_images(store, images_dir, min_age_seconds=0)
    assert removed == []
    assert fresh.exists()

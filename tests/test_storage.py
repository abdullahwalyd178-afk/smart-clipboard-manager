"""Store behavior: dedupe, pinning, retention, restart persistence."""

from datetime import datetime, timedelta, timezone

from clipboard_manager.models import IMAGE, TEXT
from clipboard_manager.storage import ClipboardStore


def iso(days_ago: float) -> str:
    return (datetime.now(timezone.utc) - timedelta(days=days_ago)).isoformat(timespec="seconds")


def test_add_text_and_dedupe(store):
    item, is_new = store.add_text("hello")
    assert is_new and item.kind == TEXT and item.text == "hello"

    dupe, is_new = store.add_text("hello")
    assert not is_new and dupe.id == item.id
    assert store.count() == 1


def test_add_image_and_dedupe(store):
    item, is_new = store.add_image("/tmp/a.png", digest="x" * 64)
    assert is_new and item.kind == IMAGE and item.image_path == "/tmp/a.png"

    _, is_new = store.add_image("/tmp/a.png", digest="x" * 64)
    assert not is_new
    assert store.count() == 1


def test_pin_toggle(store):
    item, _ = store.add_text("keep me")
    store.set_pinned(item.id, True)
    assert store.get(item.id).pinned is True
    store.set_pinned(item.id, False)
    assert store.get(item.id).pinned is False


def test_purge_expired_keeps_pinned_and_recent(store):
    store.add_text("old unpinned", created_at=iso(5))
    store.add_text("old pinned", created_at=iso(10))
    store.add_text("fresh", created_at=iso(0.1))

    old_pinned = store.list_items(10)[1]
    store.set_pinned(old_pinned.id, True)

    removed = store.purge_expired(retention_days=3)
    remaining = store.list_items(10)

    assert [i.text for i in removed] == ["old unpinned"]
    assert sorted(i.text for i in remaining) == ["fresh", "old pinned"]
    assert store.get(old_pinned.id).pinned is True


def test_pinned_items_never_expire(store):
    item, _ = store.add_text("ancient but pinned", created_at=iso(365))
    store.set_pinned(item.id, True)
    removed = store.purge_expired(retention_days=3)
    assert removed == []
    assert store.count() == 1


def test_persistence_across_restart(tmp_path):
    db = tmp_path / "history.db"
    with ClipboardStore(db) as s1:
        item, _ = s1.add_text("survives restart")
        s1.set_pinned(item.id, True)
        s1.add_image("/tmp/img.png", digest="y" * 64)

    with ClipboardStore(db) as s2:  # reopen = simulated restart
        items = s2.list_items(10)
        assert len(items) == 2
        text_item = next(i for i in items if i.kind == TEXT)
        assert text_item.text == "survives restart" and text_item.pinned is True


def test_clear_unpinned(store):
    a, _ = store.add_text("a")
    b, _ = store.add_text("b")
    store.set_pinned(b.id, True)
    removed = store.clear_unpinned()
    assert [i.text for i in removed] == ["a"]
    assert store.count() == 1 and store.get(b.id).pinned is True


def test_enforce_max_items(store):
    for i in range(5):
        store.add_text(f"item {i}", created_at=iso(0.01 * (5 - i)))
    newest = store.list_items(1)[0]
    store.set_pinned(newest.id, True)

    removed = store.enforce_max_items(2)
    assert len(removed) == 2  # 5 total - 1 pinned - 2 allowed unpinned
    assert store.count() == 3
    assert store.get(newest.id).pinned is True


def test_ocr_text_roundtrip(store):
    item, _ = store.add_image("/tmp/s.png", digest="z" * 64)
    store.set_ocr_text(item.id, "extracted text")
    assert store.get(item.id).ocr_text == "extracted text"

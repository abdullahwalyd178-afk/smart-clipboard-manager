"""Search, favorites, tags and schema-migration tests for the v0.2 store."""

import sqlite3

from clipboard_manager.models import IMAGE, TEXT
from clipboard_manager.storage import ClipboardStore


def test_search_matches_text_ocr_and_tags(store):
    a, _ = store.add_text("meet at cairo university")
    b, _ = store.add_image("/tmp/s1.png", digest="a" * 64)
    store.set_ocr_text(b.id, "derivative of x squared")
    c, _ = store.add_text("groceries: milk")
    store.set_tags(c.id, ["study", "lists"])

    assert [i.id for i in store.search("cairo")] == [a.id]
    assert [i.id for i in store.search("derivative")] == [b.id]
    assert [i.id for i in store.search("study")] == [c.id]
    assert store.search("nothing-like-this") == []


def test_search_filters_by_kind_and_favorites(store):
    t, _ = store.add_text("some text")
    i, _ = store.add_image("/tmp/s2.png", digest="b" * 64)
    store.set_favorite(i.id, True)

    assert [x.id for x in store.search(kind=TEXT)] == [t.id]
    assert [x.id for x in store.search(kind=IMAGE)] == [i.id]
    assert [x.id for x in store.search(favorites_only=True)] == [i.id]


def test_search_query_is_literal_not_like_wildcards(store):
    store.add_text("100% sure_about this")
    assert len(store.search("100%")) == 1  # % must not act as a wildcard
    assert len(store.search("sure_about")) == 1  # same for _


def test_tag_filter_matches_whole_tags_only(store):
    a, _ = store.add_text("x")
    store.set_tags(a.id, ["math"])
    b, _ = store.add_text("y")
    store.set_tags(b.id, ["mathematics"])

    assert [i.id for i in store.search(tag="math")] == [a.id]
    assert store.list_tags() == ["math", "mathematics"]


def test_favorite_is_independent_from_pin(store):
    item, _ = store.add_text("keep")
    store.set_favorite(item.id, True)
    assert store.get(item.id).favorite is True
    assert store.get(item.id).pinned is False
    store.set_pinned(item.id, True)
    store.set_favorite(item.id, False)
    assert store.get(item.id).pinned is True


def test_ocr_status_tracking(store):
    item, _ = store.add_image("/tmp/s3.png", digest="c" * 64)
    assert store.get(item.id).ocr_status is None
    store.mark_ocr_failed(item.id)
    assert store.get(item.id).ocr_status == "failed"
    store.set_ocr_text(item.id, "read this")
    assert store.get(item.id).ocr_status == "done"


def test_old_v01_database_is_migrated(tmp_path):
    """A v0.1 database (no favorite/tags/ocr_status columns) keeps working."""
    db = tmp_path / "history.db"
    conn = sqlite3.connect(db)
    conn.executescript(
        """
        CREATE TABLE items (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            kind TEXT NOT NULL,
            content_hash TEXT NOT NULL,
            text TEXT,
            image_path TEXT,
            ocr_text TEXT,
            pinned INTEGER NOT NULL DEFAULT 0,
            created_at TEXT NOT NULL
        );
        INSERT INTO items (kind, content_hash, text, pinned, created_at)
        VALUES ('text', 'h', 'legacy clip', 0, '2026-11-20T00:00:00+00:00');
        """
    )
    conn.commit()
    conn.close()

    store = ClipboardStore(db)  # opening migrates in place
    items = store.list_items(10)
    assert len(items) == 1 and items[0].text == "legacy clip"
    assert items[0].favorite is False and items[0].tags == ""
    store.set_favorite(items[0].id, True)  # new columns usable after migration
    assert store.get(items[0].id).favorite is True
    store.close()


def test_all_image_paths(store):
    store.add_image("/tmp/one.png", digest="d" * 64)
    store.add_image("/tmp/two.png", digest="e" * 64)
    store.add_text("no file")
    assert store.all_image_paths() == {"/tmp/one.png", "/tmp/two.png"}

"""SQLite-backed clipboard history store.

Everything stays local: one SQLite file plus PNG files for image clips.
Persistence across restarts comes for free from SQLite. Retention is enforced
by ``purge_expired`` which removes unpinned items older than the configured
number of days; pinned items never expire.

Schema migrations are applied idempotently in ``_migrate`` so existing v0.1
databases keep working: new columns are added with ALTER TABLE when missing.
"""

from __future__ import annotations

import sqlite3
import threading
from datetime import datetime, timedelta, timezone
from pathlib import Path

from .models import IMAGE, OCR_DONE, OCR_FAILED, TEXT, ClipboardItem

SCHEMA = """
CREATE TABLE IF NOT EXISTS items (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    kind TEXT NOT NULL CHECK(kind IN ('text', 'image')),
    content_hash TEXT NOT NULL,
    text TEXT,
    image_path TEXT,
    ocr_text TEXT,
    pinned INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_items_hash ON items(content_hash);
CREATE INDEX IF NOT EXISTS idx_items_created ON items(created_at);
"""

# Columns added after the original v0.1 schema: name -> SQL definition.
_MIGRATIONS = {
    "favorite": "ALTER TABLE items ADD COLUMN favorite INTEGER NOT NULL DEFAULT 0",
    "tags": "ALTER TABLE items ADD COLUMN tags TEXT NOT NULL DEFAULT ''",
    "ocr_status": "ALTER TABLE items ADD COLUMN ocr_status TEXT",
}

COLUMNS = (
    "id, kind, content_hash, text, image_path, ocr_text, pinned, created_at, "
    "favorite, tags, ocr_status"
)


class ClipboardStore:
    def __init__(self, db_path: str | Path):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._conn = sqlite3.connect(str(self.db_path), check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        with self._lock:
            self._conn.executescript(SCHEMA)
            self._migrate()
            self._conn.commit()

    def _migrate(self) -> None:
        existing = {
            row[1] for row in self._conn.execute("PRAGMA table_info(items)").fetchall()
        }
        for column, statement in _MIGRATIONS.items():
            if column not in existing:
                self._conn.execute(statement)

    def close(self) -> None:
        with self._lock:
            self._conn.close()

    def __enter__(self) -> "ClipboardStore":
        return self

    def __exit__(self, *exc) -> None:
        self.close()

    # -- reading -----------------------------------------------------------

    @staticmethod
    def _row_to_item(row: sqlite3.Row) -> ClipboardItem:
        return ClipboardItem(
            id=row["id"],
            kind=row["kind"],
            content_hash=row["content_hash"],
            text=row["text"],
            image_path=row["image_path"],
            ocr_text=row["ocr_text"],
            pinned=bool(row["pinned"]),
            created_at=row["created_at"],
            favorite=bool(row["favorite"]),
            tags=row["tags"] or "",
            ocr_status=row["ocr_status"],
        )

    def get_by_hash(self, content_hash: str) -> ClipboardItem | None:
        with self._lock:
            row = self._conn.execute(
                f"SELECT {COLUMNS} FROM items WHERE content_hash = ? ORDER BY id DESC LIMIT 1",
                (content_hash,),
            ).fetchone()
        return self._row_to_item(row) if row else None

    def get_by_image_path(self, image_path: str) -> ClipboardItem | None:
        with self._lock:
            row = self._conn.execute(
                f"SELECT {COLUMNS} FROM items WHERE image_path = ? ORDER BY id DESC LIMIT 1",
                (image_path,),
            ).fetchone()
        return self._row_to_item(row) if row else None

    def get(self, item_id: int) -> ClipboardItem | None:
        with self._lock:
            row = self._conn.execute(
                f"SELECT {COLUMNS} FROM items WHERE id = ?", (item_id,)
            ).fetchone()
        return self._row_to_item(row) if row else None

    def list_items(self, limit: int = 100) -> list[ClipboardItem]:
        """Newest first."""
        with self._lock:
            rows = self._conn.execute(
                f"SELECT {COLUMNS} FROM items ORDER BY id DESC LIMIT ?", (limit,)
            ).fetchall()
        return [self._row_to_item(r) for r in rows]

    def count(self) -> int:
        with self._lock:
            return self._conn.execute("SELECT COUNT(*) FROM items").fetchone()[0]

    def search(
        self,
        query: str = "",
        kind: str | None = None,
        favorites_only: bool = False,
        tag: str | None = None,
        limit: int = 200,
    ) -> list[ClipboardItem]:
        """Full-history search over text, OCR text and tags. Newest first.

        ``query`` is a case-insensitive substring matched against the text
        content, OCR text and tags. ``kind`` filters by 'text' or 'image';
        ``tag`` requires the item to carry that exact tag.
        """
        clauses: list[str] = []
        params: list[object] = []
        if query:
            clauses.append(
                "(text LIKE ? ESCAPE '\\' OR ocr_text LIKE ? ESCAPE '\\'"
                " OR tags LIKE ? ESCAPE '\\')"
            )
            needle = _like_escape(query)
            params += [needle, needle, needle]
        if kind:
            clauses.append("kind = ?")
            params.append(kind)
        if favorites_only:
            clauses.append("favorite = 1")
        if tag:
            clauses.append("(',' || tags || ',') LIKE ? ESCAPE '\\'")
            params.append(_like_escape(tag, wrap=True))
        where = (" WHERE " + " AND ".join(clauses)) if clauses else ""
        params.append(limit)
        with self._lock:
            rows = self._conn.execute(
                f"SELECT {COLUMNS} FROM items{where} ORDER BY id DESC LIMIT ?",
                params,
            ).fetchall()
        return [self._row_to_item(r) for r in rows]

    def list_tags(self) -> list[str]:
        """All distinct tags in use, alphabetically."""
        with self._lock:
            rows = self._conn.execute(
                "SELECT DISTINCT tags FROM items WHERE tags <> ''"
            ).fetchall()
        tags: set[str] = set()
        for (blob,) in rows:
            tags.update(t.strip() for t in blob.split(",") if t.strip())
        return sorted(tags, key=str.lower)

    def all_image_paths(self) -> set[str]:
        """Image file paths referenced by any stored item (orphan detection)."""
        with self._lock:
            rows = self._conn.execute(
                "SELECT image_path FROM items WHERE image_path IS NOT NULL"
            ).fetchall()
        return {r[0] for r in rows}

    # -- writing -----------------------------------------------------------

    def _insert(self, item: ClipboardItem) -> int:
        with self._lock:
            cur = self._conn.execute(
                "INSERT INTO items (kind, content_hash, text, image_path, ocr_text, pinned,"
                " created_at, favorite, tags, ocr_status)"
                " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    item.kind,
                    item.content_hash,
                    item.text,
                    item.image_path,
                    item.ocr_text,
                    int(item.pinned),
                    item.created_at,
                    int(item.favorite),
                    item.tags,
                    item.ocr_status,
                ),
            )
            self._conn.commit()
            return cur.lastrowid

    def add_text(self, text: str, created_at: str | None = None) -> tuple[ClipboardItem, bool]:
        """Add a text clip. Returns (item, is_new); duplicates are deduped by hash."""
        digest = ClipboardItem.hash_text(text)
        existing = self.get_by_hash(digest)
        if existing is not None:
            return existing, False
        item = ClipboardItem(
            id=None,
            kind=TEXT,
            content_hash=digest,
            text=text,
            created_at=created_at or ClipboardItem.utcnow_iso(),
        )
        item.id = self._insert(item)
        return item, True

    def add_image(
        self, image_path: str, digest: str, created_at: str | None = None
    ) -> tuple[ClipboardItem, bool]:
        """Add an image clip. ``digest`` is the SHA-256 of the PNG bytes."""
        existing = self.get_by_hash(digest)
        if existing is not None:
            return existing, False
        item = ClipboardItem(
            id=None,
            kind=IMAGE,
            content_hash=digest,
            image_path=image_path,
            created_at=created_at or ClipboardItem.utcnow_iso(),
        )
        item.id = self._insert(item)
        return item, True

    def set_pinned(self, item_id: int, pinned: bool) -> None:
        with self._lock:
            self._conn.execute(
                "UPDATE items SET pinned = ? WHERE id = ?", (int(pinned), item_id)
            )
            self._conn.commit()

    def set_favorite(self, item_id: int, favorite: bool) -> None:
        with self._lock:
            self._conn.execute(
                "UPDATE items SET favorite = ? WHERE id = ?", (int(favorite), item_id)
            )
            self._conn.commit()

    def set_tags(self, item_id: int, tags: list[str] | str) -> None:
        if isinstance(tags, list):
            tags = ",".join(t.strip() for t in tags if t.strip())
        with self._lock:
            self._conn.execute(
                "UPDATE items SET tags = ? WHERE id = ?", (tags, item_id)
            )
            self._conn.commit()

    def set_ocr_text(self, item_id: int, ocr_text: str) -> None:
        """Store OCR output. Marks the item's OCR status as done."""
        with self._lock:
            self._conn.execute(
                "UPDATE items SET ocr_text = ?, ocr_status = ? WHERE id = ?",
                (ocr_text, OCR_DONE, item_id),
            )
            self._conn.commit()

    def set_ocr_status(self, item_id: int, status: str | None) -> None:
        with self._lock:
            self._conn.execute(
                "UPDATE items SET ocr_status = ? WHERE id = ?", (status, item_id)
            )
            self._conn.commit()

    def mark_ocr_failed(self, item_id: int) -> None:
        self.set_ocr_status(item_id, OCR_FAILED)

    def delete(self, item_id: int) -> ClipboardItem | None:
        item = self.get(item_id)
        if item is None:
            return None
        with self._lock:
            self._conn.execute("DELETE FROM items WHERE id = ?", (item_id,))
            self._conn.commit()
        return item

    # -- retention ---------------------------------------------------------

    def purge_expired(self, retention_days: int, now: datetime | None = None) -> list[ClipboardItem]:
        """Delete unpinned items older than retention_days. Pinned items never expire.

        Returns the deleted items so the caller can remove their image files.
        """
        now = now or datetime.now(timezone.utc)
        cutoff = (now - timedelta(days=retention_days)).isoformat(timespec="seconds")
        with self._lock:
            rows = self._conn.execute(
                f"SELECT {COLUMNS} FROM items WHERE pinned = 0 AND created_at < ?",
                (cutoff,),
            ).fetchall()
            items = [self._row_to_item(r) for r in rows]
            if items:
                self._conn.executemany(
                    "DELETE FROM items WHERE id = ?", [(i.id,) for i in items]
                )
                self._conn.commit()
        return items

    def enforce_max_items(self, max_items: int) -> list[ClipboardItem]:
        """Delete oldest unpinned items beyond the cap. Returns deleted items."""
        if max_items <= 0:
            return []
        with self._lock:
            rows = self._conn.execute(
                f"SELECT {COLUMNS} FROM items WHERE pinned = 0 ORDER BY id DESC LIMIT -1 OFFSET ?",
                (max_items,),
            ).fetchall()
            items = [self._row_to_item(r) for r in rows]
            if items:
                self._conn.executemany(
                    "DELETE FROM items WHERE id = ?", [(i.id,) for i in items]
                )
                self._conn.commit()
        return items

    def clear_unpinned(self) -> list[ClipboardItem]:
        """Delete every unpinned item. Pinned items are kept."""
        with self._lock:
            rows = self._conn.execute(
                f"SELECT {COLUMNS} FROM items WHERE pinned = 0"
            ).fetchall()
            items = [self._row_to_item(r) for r in rows]
            self._conn.execute("DELETE FROM items WHERE pinned = 0")
            self._conn.commit()
        return items


def _like_escape(query: str, wrap: bool = False) -> str:
    """Escape a user query for a LIKE pattern (substring match, no wildcards)."""
    escaped = query.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    return f"%,{escaped},%" if wrap else f"%{escaped}%"

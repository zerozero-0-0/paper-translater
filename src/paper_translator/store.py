import json
import sqlite3
import time
from contextlib import closing
from pathlib import Path

from .pdf import TRANSLATED_KINDS, Segment

SCHEMA = """
CREATE TABLE IF NOT EXISTS papers (
    id TEXT PRIMARY KEY,
    filename TEXT NOT NULL,
    title TEXT NOT NULL,
    pages TEXT NOT NULL,
    status TEXT NOT NULL,
    error TEXT,
    created_at REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS segments (
    paper_id TEXT NOT NULL REFERENCES papers(id) ON DELETE CASCADE,
    idx INTEGER NOT NULL,
    kind TEXT NOT NULL,
    page INTEGER NOT NULL,
    boxes TEXT NOT NULL,
    source TEXT NOT NULL,
    translation TEXT,
    status TEXT NOT NULL,
    PRIMARY KEY (paper_id, idx)
);
"""


class Store:
    def __init__(self, path: Path):
        self.path = path
        path.parent.mkdir(parents=True, exist_ok=True)
        with closing(self._connect()) as db, db:
            db.execute("PRAGMA journal_mode=WAL")
            db.executescript(SCHEMA)

    def _connect(self) -> sqlite3.Connection:
        db = sqlite3.connect(self.path)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA foreign_keys=ON")
        return db

    def add_paper(self, paper_id: str, filename: str, title: str, pages: list, segments: list[Segment]) -> None:
        rows = [
            (
                paper_id,
                idx,
                s.kind,
                s.page,
                json.dumps(s.boxes),
                s.source,
                "pending" if s.kind in TRANSLATED_KINDS else "skipped",
            )
            for idx, s in enumerate(segments)
        ]
        with closing(self._connect()) as db, db:
            db.execute(
                "INSERT INTO papers VALUES (?, ?, ?, ?, 'queued', NULL, ?)",
                (paper_id, filename, title, json.dumps(pages), time.time()),
            )
            db.executemany(
                "INSERT INTO segments (paper_id, idx, kind, page, boxes, source, status) VALUES (?, ?, ?, ?, ?, ?, ?)",
                rows,
            )

    def _paper_dict(self, db: sqlite3.Connection, row: sqlite3.Row) -> dict:
        counts = db.execute(
            "SELECT count(*) AS total, count(*) FILTER (WHERE status IN ('done', 'failed')) AS done, "
            "count(*) FILTER (WHERE status = 'failed') AS failed "
            "FROM segments WHERE paper_id = ? AND status != 'skipped'",
            (row["id"],),
        ).fetchone()
        return {**dict(row), "pages": json.loads(row["pages"]), **dict(counts)}

    def paper(self, paper_id: str) -> dict | None:
        with closing(self._connect()) as db:
            row = db.execute("SELECT * FROM papers WHERE id = ?", (paper_id,)).fetchone()
            return self._paper_dict(db, row) if row else None

    def papers(self) -> list[dict]:
        with closing(self._connect()) as db:
            rows = db.execute("SELECT * FROM papers ORDER BY created_at DESC").fetchall()
            return [self._paper_dict(db, row) for row in rows]

    def segments(self, paper_id: str) -> list[dict]:
        with closing(self._connect()) as db:
            rows = db.execute("SELECT * FROM segments WHERE paper_id = ? ORDER BY idx", (paper_id,)).fetchall()
        return [{**dict(row), "boxes": json.loads(row["boxes"])} for row in rows]

    def segment(self, paper_id: str, idx: int) -> dict | None:
        with closing(self._connect()) as db:
            row = db.execute("SELECT * FROM segments WHERE paper_id = ? AND idx = ?", (paper_id, idx)).fetchone()
        return {**dict(row), "boxes": json.loads(row["boxes"])} if row else None

    def next_pending(self, paper_id: str) -> dict | None:
        with closing(self._connect()) as db:
            row = db.execute(
                "SELECT idx, kind, source FROM segments WHERE paper_id = ? AND status = 'pending' ORDER BY idx LIMIT 1",
                (paper_id,),
            ).fetchone()
        return dict(row) if row else None

    def history(self, paper_id: str, idx: int, limit: int) -> list[tuple[str, str]]:
        """訳語を揃えるための直前の本文と訳文を、古い順に返す。"""
        with closing(self._connect()) as db:
            rows = db.execute(
                "SELECT source, translation FROM segments "
                "WHERE paper_id = ? AND idx < ? AND kind = 'text' AND status = 'done' ORDER BY idx DESC LIMIT ?",
                (paper_id, idx, limit),
            ).fetchall()
        return [(row["source"], row["translation"]) for row in reversed(rows)]

    def save_translation(self, paper_id: str, idx: int, translation: str, status: str) -> None:
        with closing(self._connect()) as db, db:
            db.execute(
                "UPDATE segments SET translation = ?, status = ? WHERE paper_id = ? AND idx = ?",
                (translation, status, paper_id, idx),
            )

    def set_status(self, paper_id: str, status: str, error: str | None = None) -> None:
        with closing(self._connect()) as db, db:
            db.execute("UPDATE papers SET status = ?, error = ? WHERE id = ?", (status, error, paper_id))

    def next_queued(self) -> str | None:
        with closing(self._connect()) as db:
            row = db.execute(
                "SELECT id FROM papers WHERE status IN ('queued', 'translating') ORDER BY created_at LIMIT 1"
            ).fetchone()
        return row["id"] if row else None

    def pause_unfinished(self) -> None:
        """起動しただけで GPU を使わないよう、前回の続きは手動再開にする。"""
        with closing(self._connect()) as db, db:
            db.execute("UPDATE papers SET status = 'paused' WHERE status IN ('queued', 'translating')")

    def retry_failed(self, paper_id: str) -> None:
        with closing(self._connect()) as db, db:
            db.execute(
                "UPDATE segments SET status = 'pending', translation = NULL WHERE paper_id = ? AND status = 'failed'",
                (paper_id,),
            )

    def delete_paper(self, paper_id: str) -> None:
        with closing(self._connect()) as db, db:
            db.execute("DELETE FROM papers WHERE id = ?", (paper_id,))

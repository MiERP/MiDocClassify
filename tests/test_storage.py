import csv
import sqlite3
from pathlib import Path

from phanloaivanban.models import DocumentRecord
from phanloaivanban.storage import export_csv, init_db, upsert_record


def test_upsert_and_export_preserve_wiki_path_and_link_goc(tmp_path: Path) -> None:
    db_path = tmp_path / "records.sqlite"
    csv_path = tmp_path / "records.csv"
    init_db(db_path)
    record = DocumentRecord(
        original_path=Path("orig.pdf"),
        file_name="orig.pdf",
        file_hash="hash-1",
        link_goc="file:///orig.pdf",
        wiki_path="data/wiki/x.md",
    )

    upsert_record(db_path, record)
    export_csv(db_path, csv_path)

    with sqlite3.connect(db_path) as conn:
        row = conn.execute(
            "SELECT link_goc, wiki_path FROM documents WHERE file_hash = ?",
            ("hash-1",),
        ).fetchone()
    with csv_path.open(encoding="utf-8-sig", newline="") as handle:
        exported = next(csv.DictReader(handle))
    assert row == ("file:///orig.pdf", "data/wiki/x.md")
    assert exported["link_goc"] == "file:///orig.pdf"
    assert exported["wiki_path"] == "data/wiki/x.md"


def test_init_db_migrates_legacy_database_without_wiki_path(tmp_path: Path) -> None:
    db_path = tmp_path / "legacy.sqlite"
    csv_path = tmp_path / "legacy.csv"
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            """
            CREATE TABLE documents (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                original_path TEXT NOT NULL,
                file_name TEXT NOT NULL,
                file_hash TEXT NOT NULL UNIQUE,
                so_van_ban TEXT,
                ten_van_ban TEXT,
                co_quan_phat_hanh TEXT,
                ngay_ban_hanh TEXT,
                loai_van_ban TEXT,
                trich_yeu TEXT,
                link_goc TEXT,
                extracted_text TEXT,
                extraction_status TEXT,
                review_reason TEXT DEFAULT 'ok',
                ocr_engine TEXT,
                confidence REAL,
                needs_review INTEGER
            )
            """
        )
    record = DocumentRecord(
        original_path=Path("legacy.pdf"),
        file_name="legacy.pdf",
        file_hash="hash-legacy",
        link_goc="file:///legacy.pdf",
        wiki_path="data/wiki/legacy.md",
    )

    init_db(db_path)
    upsert_record(db_path, record)
    export_csv(db_path, csv_path)

    with sqlite3.connect(db_path) as conn:
        columns = {row[1] for row in conn.execute("PRAGMA table_info(documents)")}
        row = conn.execute(
            "SELECT link_goc, wiki_path FROM documents WHERE file_hash = ?",
            ("hash-legacy",),
        ).fetchone()
    with csv_path.open(encoding="utf-8-sig", newline="") as handle:
        exported = next(csv.DictReader(handle))
    assert "wiki_path" in columns
    assert row == ("file:///legacy.pdf", "data/wiki/legacy.md")
    assert exported["link_goc"] == "file:///legacy.pdf"
    assert exported["wiki_path"] == "data/wiki/legacy.md"

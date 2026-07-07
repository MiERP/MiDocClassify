from __future__ import annotations

import csv
import sqlite3
from dataclasses import asdict
from pathlib import Path

from .models import DocumentRecord

FIELDS = [
    "so_van_ban",
    "ten_van_ban",
    "co_quan_phat_hanh",
    "ngay_ban_hanh",
    "loai_van_ban",
    "trich_yeu",
    "link_goc",
    "wiki_path",
    "confidence",
    "needs_review",
    "original_path",
    "extraction_status",
    "review_reason",
]


def init_db(db_path: Path) -> None:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS documents (
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
                wiki_path TEXT,
                extracted_text TEXT,
                extraction_status TEXT,
                review_reason TEXT DEFAULT 'ok',
                ocr_engine TEXT,
                confidence REAL,
                needs_review INTEGER
            )
            """
        )
        columns = {row[1] for row in conn.execute("PRAGMA table_info(documents)")}
        if "review_reason" not in columns:
            conn.execute("ALTER TABLE documents ADD COLUMN review_reason TEXT DEFAULT 'ok'")
        if "wiki_path" not in columns:
            conn.execute("ALTER TABLE documents ADD COLUMN wiki_path TEXT")


def upsert_record(db_path: Path, record: DocumentRecord) -> None:
    data = asdict(record)
    data["original_path"] = str(record.original_path)
    data["needs_review"] = int(record.needs_review)
    columns = ", ".join(data)
    placeholders = ", ".join(f":{key}" for key in data)
    updates = ", ".join(f"{key}=excluded.{key}" for key in data if key != "file_hash")
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            f"INSERT INTO documents ({columns}) VALUES ({placeholders}) "
            f"ON CONFLICT(file_hash) DO UPDATE SET {updates}",
            data,
        )


def folder_file_hashes(db_path: Path, folder: Path) -> dict[str, str]:
    if not db_path.exists():
        return {}
    folder_text = str(folder).rstrip("\\/")
    with sqlite3.connect(db_path) as conn:
        rows = conn.execute(
            "SELECT original_path, file_hash FROM documents WHERE original_path LIKE ? OR original_path LIKE ?",
            (f"{folder_text}\\%", f"{folder_text}/%"),
        )
    return {str(path): str(file_hash) for path, file_hash in rows}


def delete_records_by_paths(db_path: Path, paths: list[Path]) -> int:
    if not paths or not db_path.exists():
        return 0
    values = [(str(path),) for path in paths]
    with sqlite3.connect(db_path) as conn:
        conn.executemany("DELETE FROM documents WHERE original_path = ?", values)
        return int(conn.total_changes)


def export_csv(db_path: Path, csv_path: Path) -> None:
    csv_path.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(db_path) as conn, csv_path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=FIELDS)
        writer.writeheader()
        for row in conn.execute(f"SELECT {', '.join(FIELDS)} FROM documents ORDER BY file_name"):
            writer.writerow(dict(zip(FIELDS, row)))

from __future__ import annotations

import csv
import sqlite3
from contextlib import contextmanager
from dataclasses import asdict
from pathlib import Path

from .models import DocumentRecord

@contextmanager
def _connect(db_path: Path):
    conn = sqlite3.connect(db_path)
    try:
        with conn:
            yield conn
    finally:
        conn.close()

DOCUMENT_COLUMNS = [
    "original_path", "file_name", "file_hash", "file_size", "mtime_ns",
    "extractor_version", "indexed_at", "so_van_ban", "ten_van_ban",
    "co_quan_phat_hanh", "ngay_ban_hanh", "loai_van_ban", "trich_yeu",
    "link_goc", "wiki_path", "extracted_text", "extraction_status",
    "review_reason", "ocr_engine", "confidence", "needs_review",
]

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
    with _connect(db_path) as conn:
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA synchronous=NORMAL")
        conn.execute("PRAGMA busy_timeout=5000")
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS documents (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                original_path TEXT NOT NULL,
                file_name TEXT NOT NULL,
                file_hash TEXT NOT NULL,
                file_size INTEGER NOT NULL DEFAULT 0,
                mtime_ns INTEGER NOT NULL DEFAULT 0,
                extractor_version TEXT NOT NULL DEFAULT '',
                indexed_at TEXT NOT NULL DEFAULT '',
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
        additions = {
            "file_size": "INTEGER NOT NULL DEFAULT 0",
            "mtime_ns": "INTEGER NOT NULL DEFAULT 0",
            "extractor_version": "TEXT NOT NULL DEFAULT ''",
            "indexed_at": "TEXT NOT NULL DEFAULT ''",
        }
        for name, definition in additions.items():
            if name not in columns:
                conn.execute(f"ALTER TABLE documents ADD COLUMN {name} {definition}")
        _remove_legacy_unique_hash(conn)
        conn.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_documents_original_path ON documents(original_path)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_documents_file_hash ON documents(file_hash)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_documents_needs_review ON documents(needs_review)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_documents_so_van_ban ON documents(so_van_ban)")

def _remove_legacy_unique_hash(conn: sqlite3.Connection) -> None:
    unique_hash = False
    for _, name, unique, *_ in conn.execute("PRAGMA index_list(documents)"):
        columns = [row[2] for row in conn.execute(f'PRAGMA index_info("{name}")')]
        if unique and columns == ["file_hash"]:
            unique_hash = True
            break
    if not unique_hash:
        return
    columns = [row[1] for row in conn.execute("PRAGMA table_info(documents)")]
    select_columns = ", ".join(columns)
    conn.execute("ALTER TABLE documents RENAME TO documents_legacy")
    conn.execute(
        """
        CREATE TABLE documents (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            original_path TEXT NOT NULL,
            file_name TEXT NOT NULL,
            file_hash TEXT NOT NULL,
            file_size INTEGER NOT NULL DEFAULT 0,
            mtime_ns INTEGER NOT NULL DEFAULT 0,
            extractor_version TEXT NOT NULL DEFAULT '',
            indexed_at TEXT NOT NULL DEFAULT '',
            so_van_ban TEXT, ten_van_ban TEXT, co_quan_phat_hanh TEXT,
            ngay_ban_hanh TEXT, loai_van_ban TEXT, trich_yeu TEXT,
            link_goc TEXT, wiki_path TEXT, extracted_text TEXT,
            extraction_status TEXT, review_reason TEXT DEFAULT 'ok',
            ocr_engine TEXT, confidence REAL, needs_review INTEGER
        )
        """
    )
    conn.execute(f"INSERT INTO documents ({select_columns}) SELECT {select_columns} FROM documents_legacy")
    conn.execute("DROP TABLE documents_legacy")

def upsert_record(db_path: Path, record: DocumentRecord) -> None:
    upsert_records(db_path, [record])

def upsert_records(db_path: Path, records: list[DocumentRecord]) -> None:
    if not records:
        return
    rows = [_record_data(record) for record in records]
    columns = ", ".join(DOCUMENT_COLUMNS)
    placeholders = ", ".join(f":{key}" for key in DOCUMENT_COLUMNS)
    updates = ", ".join(f"{key}=excluded.{key}" for key in DOCUMENT_COLUMNS if key != "original_path")
    with _connect(db_path) as conn:
        conn.execute("PRAGMA busy_timeout=5000")
        conn.executemany(
            f"INSERT INTO documents ({columns}) VALUES ({placeholders}) "
            f"ON CONFLICT(original_path) DO UPDATE SET {updates}",
            rows,
        )

def _record_data(record: DocumentRecord) -> dict[str, object]:
    data = asdict(record)
    data["original_path"] = str(record.original_path)
    data["needs_review"] = int(record.needs_review)
    return data

def all_records(db_path: Path) -> list[DocumentRecord]:
    if not db_path.exists():
        return []
    with _connect(db_path) as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            """
            SELECT original_path, file_name, file_hash, file_size, mtime_ns,
                   extractor_version, indexed_at, so_van_ban, ten_van_ban,
                   co_quan_phat_hanh, ngay_ban_hanh, loai_van_ban, trich_yeu,
                   link_goc, wiki_path, extracted_text, extraction_status,
                   review_reason, ocr_engine, confidence, needs_review
            FROM documents
            ORDER BY file_name
            """
        ).fetchall()
    return [
        DocumentRecord(
            original_path=Path(row["original_path"]),
            file_name=row["file_name"] or "",
            file_hash=row["file_hash"] or "",
            file_size=int(row["file_size"] or 0),
            mtime_ns=int(row["mtime_ns"] or 0),
            extractor_version=row["extractor_version"] or "",
            indexed_at=row["indexed_at"] or "",
            so_van_ban=row["so_van_ban"],
            ten_van_ban=row["ten_van_ban"],
            co_quan_phat_hanh=row["co_quan_phat_hanh"],
            ngay_ban_hanh=row["ngay_ban_hanh"],
            loai_van_ban=row["loai_van_ban"],
            trich_yeu=row["trich_yeu"],
            link_goc=row["link_goc"],
            wiki_path=row["wiki_path"],
            extracted_text=row["extracted_text"] or "",
            extraction_status=row["extraction_status"] or "ok",
            review_reason=row["review_reason"] or "ok",
            ocr_engine=row["ocr_engine"],
            confidence=float(row["confidence"] or 0.0),
            needs_review=bool(row["needs_review"]),
        )
        for row in rows
    ]

def folder_file_hashes(db_path: Path, folder: Path) -> dict[str, str]:
    if not db_path.exists():
        return {}
    folder_text = str(folder).rstrip("\\/")
    with _connect(db_path) as conn:
        rows = conn.execute(
            "SELECT original_path, file_hash FROM documents WHERE original_path LIKE ? OR original_path LIKE ?",
            (f"{folder_text}\\%", f"{folder_text}/%"),
        ).fetchall()
    return {str(path): str(file_hash) for path, file_hash in rows}

def folder_file_states(db_path: Path, folder: Path) -> dict[str, tuple[int, int, str]]:
    if not db_path.exists():
        return {}
    folder_text = str(folder).rstrip("\\/")
    with _connect(db_path) as conn:
        rows = conn.execute(
            "SELECT original_path, file_size, mtime_ns, extractor_version FROM documents WHERE original_path LIKE ? OR original_path LIKE ?",
            (f"{folder_text}\\%", f"{folder_text}/%"),
        ).fetchall()
    return {str(path): (int(size or 0), int(mtime or 0), str(version or "")) for path, size, mtime, version in rows}

def apply_record_changes(db_path: Path, records: list[DocumentRecord], deleted_paths: list[Path]) -> int:
    rows = [_record_data(record) for record in records]
    columns = ", ".join(DOCUMENT_COLUMNS)
    placeholders = ", ".join(f":{key}" for key in DOCUMENT_COLUMNS)
    updates = ", ".join(f"{key}=excluded.{key}" for key in DOCUMENT_COLUMNS if key != "original_path")
    with _connect(db_path) as conn:
        conn.execute("PRAGMA busy_timeout=5000")
        before = conn.total_changes
        if deleted_paths:
            conn.executemany("DELETE FROM documents WHERE original_path = ?", [(str(path),) for path in deleted_paths])
        if rows:
            conn.executemany(
                f"INSERT INTO documents ({columns}) VALUES ({placeholders}) "
                f"ON CONFLICT(original_path) DO UPDATE SET {updates}",
                rows,
            )
        return int(conn.total_changes - before)
































def wiki_paths_by_original_paths(db_path: Path, paths: list[Path]) -> list[str]:
    if not paths or not db_path.exists():
        return []
    wiki_paths: list[str] = []
    with _connect(db_path) as conn:
        for path in paths:
            row = conn.execute("SELECT wiki_path FROM documents WHERE original_path = ?", (str(path),)).fetchone()
            if row and row[0]:
                wiki_paths.append(str(row[0]))
    return wiki_paths

def delete_records_by_paths(db_path: Path, paths: list[Path]) -> int:
    if not paths or not db_path.exists():
        return 0
    values = [(str(path),) for path in paths]
    with _connect(db_path) as conn:
        conn.executemany("DELETE FROM documents WHERE original_path = ?", values)
        return int(conn.total_changes)

def export_csv(db_path: Path, csv_path: Path) -> None:
    csv_path.parent.mkdir(parents=True, exist_ok=True)
    with _connect(db_path) as conn, csv_path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=FIELDS)
        writer.writeheader()
        for row in conn.execute(f"SELECT {', '.join(FIELDS)} FROM documents ORDER BY file_name"):
            writer.writerow(dict(zip(FIELDS, row)))

def load_document_rows(db_path: Path, folder: Path | None = None) -> list[dict[str, object]]:
    if not db_path.exists():
        return []
    where = ""
    params: tuple[str, ...] = ()
    if folder is not None:
        folder_text = str(folder).rstrip("\\/")
        where = " WHERE original_path LIKE ? OR original_path LIKE ?"
        params = (f"{folder_text}\\%", f"{folder_text}/%")
    with _connect(db_path) as conn:
        columns = {row[1] for row in conn.execute("PRAGMA table_info(documents)")}
        selected = [field if field in columns else "''" for field in FIELDS]
        rows = conn.execute(f"SELECT {', '.join(selected)} FROM documents{where} ORDER BY file_name", params)
        return [dict(zip(FIELDS, row)) for row in rows]

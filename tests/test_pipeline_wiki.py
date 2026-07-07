from __future__ import annotations

import csv
import sqlite3
from pathlib import Path

from phanloaivanban.pipeline import scan_folder, sync_folder

SAMPLE_67 = (
    "QUỐC HỘI\n"
    "Số: 67/2006/QH11\n"
    "CỘNG HÒA XÃ HỘI CHỦ NGHĨA VIỆT NAM\n"
    "Độc lập - Tự do - Hạnh phúc\n"
    "Hà Nội, ngày 29 tháng 06 năm 2006\n"
    "LUẬT\n"
    "CÔNG NGHỆ THÔNG TIN\n"
)


def test_scan_folder_extracts_metadata_without_wiki(tmp_path: Path) -> None:
    input_dir = tmp_path / "input"
    input_dir.mkdir()
    (input_dir / "67_2006_QH11.txt").write_text(SAMPLE_67, encoding="utf-8")

    db_path = tmp_path / "db.sqlite"
    csv_path = tmp_path / "export.csv"
    records = scan_folder(input_dir, db_path, csv_path=csv_path, wiki_root=tmp_path / "wiki")

    assert len(records) == 1
    record = records[0]
    assert record.so_van_ban == "67/2006/QH11"
    assert record.co_quan_phat_hanh == "Quốc hội"
    assert record.ngay_ban_hanh == "2006-06-29"
    assert record.loai_van_ban == "Luật"
    assert record.wiki_path is None
    assert not (tmp_path / "wiki").exists()

    with sqlite3.connect(db_path) as conn:
        row = conn.execute(
            "SELECT so_van_ban, wiki_path FROM documents WHERE file_hash = ?",
            (record.file_hash,),
        ).fetchone()
    assert row == ("67/2006/QH11", None)

    with csv_path.open(encoding="utf-8-sig", newline="") as handle:
        exported = next(csv.DictReader(handle))
    assert exported["so_van_ban"] == "67/2006/QH11"
    assert exported["wiki_path"] == ""


def test_sync_folder_processes_only_added_and_deleted_files(tmp_path: Path) -> None:
    input_dir = tmp_path / "input"
    input_dir.mkdir()
    first = input_dir / "first.txt"
    first.write_text("QUỐC HỘI\nSố: 01/2026/QH15\nLUẬT\nTEST", encoding="utf-8")
    db_path = tmp_path / "db.sqlite"

    records, deleted = sync_folder(input_dir, db_path, wiki_root=tmp_path / "wiki")
    assert len(records) == 1
    assert deleted == 0

    records, deleted = sync_folder(input_dir, db_path, wiki_root=tmp_path / "wiki")
    assert records == []
    assert deleted == 0

    second = input_dir / "second.txt"
    second.write_text("QUỐC HỘI\nSố: 02/2026/QH15\nLUẬT\nTEST", encoding="utf-8")
    first.unlink()
    records, deleted = sync_folder(input_dir, db_path, wiki_root=tmp_path / "wiki")
    assert [record.file_name for record in records] == ["second.txt"]
    assert deleted == 1


def test_scan_folder_reports_metadata_phases(tmp_path: Path) -> None:
    input_dir = tmp_path / "input"
    input_dir.mkdir()
    (input_dir / "67_2006_QH11.txt").write_text(SAMPLE_67, encoding="utf-8")
    events: list[tuple[int, int, str, str]] = []

    def progress(current: int, total: int, path: Path, action: str) -> None:
        events.append((current, total, path.name, action))

    scan_folder(
        folder=input_dir,
        db_path=tmp_path / "db.sqlite",
        csv_path=tmp_path / "export.csv",
        wiki_root=tmp_path / "wiki",
        progress_callback=progress,
    )

    actions = [event[3] for event in events]
    assert "Đang OCR/trích xuất metadata" in actions
    assert "Đang bổ sung metadata" in actions
    assert "Đang lưu DB" in actions
    assert "Đang xuất CSV" in actions
    assert "Đang tạo wiki" not in actions
    assert "Đang chạy LLM" not in actions

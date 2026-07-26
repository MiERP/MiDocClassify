from __future__ import annotations

import csv
import sqlite3
from pathlib import Path

from phanloaivanban.pipeline import ScanOptions, scan_folder, sync_folder

SAMPLE_67 = (
    "QUỐC HỘI\n"
    "Số: 67/2006/QH11\n"
    "CỘNG HÒA XÃ HỘI CHỦ NGHĨA VIỆT NAM\n"
    "Độc lập - Tự do - Hạnh phúc\n"
    "Hà Nội, ngày 29 tháng 06 năm 2006\n"
    "LUẬT\n"
    "CÔNG NGHỆ THÔNG TIN\n"
)


def test_scan_folder_extracts_metadata_and_writes_wiki(tmp_path: Path) -> None:

    input_dir = tmp_path / "input"
    input_dir.mkdir()
    (input_dir / "67_2006_QH11.txt").write_text(SAMPLE_67, encoding="utf-8")

    db_path = tmp_path / "db.sqlite"
    csv_path = tmp_path / "export.csv"
    records = scan_folder(input_dir, db_path, csv_path=csv_path, wiki_root=tmp_path / "wiki", write_wiki=True)

    assert len(records) == 1
    record = records[0]
    assert record.so_van_ban == "67/2006/QH11"
    assert record.co_quan_phat_hanh == "Quốc hội"
    assert record.ngay_ban_hanh == "2006-06-29"
    assert record.loai_van_ban == "Luật"
    assert record.wiki_path is not None
    wiki_path = Path(record.wiki_path)
    assert wiki_path.name == "67_2006_QH11.md"
    assert wiki_path.exists()
    markdown = wiki_path.read_text(encoding="utf-8")
    assert "type: legal_document_source" in markdown
    assert "so_van_ban" in markdown
    assert "## Nội dung văn bản" in markdown
    assert "CÔNG NGHỆ THÔNG TIN" in markdown
    index = (tmp_path / "wiki" / "index.md").read_text(encoding="utf-8")
    assert "67/2006/QH11" in index
    assert f"]({wiki_path.name})" in index
    log = (tmp_path / "wiki" / "log.md").read_text(encoding="utf-8")
    assert "ingest" in log
    assert "67/2006/QH11" in log

    with sqlite3.connect(db_path) as conn:
        row = conn.execute(
            "SELECT so_van_ban, wiki_path FROM documents WHERE file_hash = ?",
            (record.file_hash,),
        ).fetchone()
    assert row == ("67/2006/QH11", record.wiki_path)

    with csv_path.open(encoding="utf-8-sig", newline="") as handle:
        exported = next(csv.DictReader(handle))
    assert exported["so_van_ban"] == "67/2006/QH11"
    assert exported["wiki_path"] == record.wiki_path



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


def test_sync_folder_index_lists_all_current_documents_after_incremental_add(tmp_path: Path) -> None:
    input_dir = tmp_path / "input"
    input_dir.mkdir()
    first = input_dir / "first.txt"
    first.write_text("QUỐC HỘI\nSố: 01/2026/QH15\nLUẬT\nTEST", encoding="utf-8")
    db_path = tmp_path / "db.sqlite"
    wiki_root = tmp_path / "wiki"

    sync_folder(input_dir, db_path, wiki_root=wiki_root, write_wiki=True)
    assert "01/2026/QH15" in (wiki_root / "index.md").read_text(encoding="utf-8")

    second = input_dir / "second.txt"
    second.write_text("QUỐC HỘI\nSố: 02/2026/QH15\nLUẬT\nTEST", encoding="utf-8")
    sync_folder(input_dir, db_path, wiki_root=wiki_root, write_wiki=True)

    index = (wiki_root / "index.md").read_text(encoding="utf-8")
    assert "01/2026/QH15" in index
    assert "02/2026/QH15" in index


def test_sync_folder_removes_stale_wiki_for_deleted_file(tmp_path: Path) -> None:
    input_dir = tmp_path / "input"
    input_dir.mkdir()
    first = input_dir / "first.txt"
    first.write_text("QUỐC HỘI\nSố: 01/2026/QH15\nLUẬT\nTEST", encoding="utf-8")
    db_path = tmp_path / "db.sqlite"
    wiki_root = tmp_path / "wiki"

    records, deleted = sync_folder(input_dir, db_path, wiki_root=wiki_root, write_wiki=True)
    assert deleted == 0
    old_wiki_path = Path(records[0].wiki_path or "")
    assert old_wiki_path.exists()

    first.unlink()
    records, deleted = sync_folder(input_dir, db_path, wiki_root=wiki_root, write_wiki=True)

    assert records == []
    assert deleted == 1
    assert not old_wiki_path.exists()
    index = (wiki_root / "index.md").read_text(encoding="utf-8")
    assert "01/2026/QH15" not in index
    log = (wiki_root / "log.md").read_text(encoding="utf-8")
    assert "delete" in log
    assert "first.txt" in log

def test_duplicate_document_numbers_share_one_wiki_file(tmp_path: Path) -> None:
    input_dir = tmp_path / "input"
    input_dir.mkdir()
    (input_dir / "same.docx.txt").write_text("QUỐC HỘI\nSố: 99/2025/NĐ-CP\nNGHỊ ĐỊNH\nBẢN DOCX ĐẦY ĐỦ " + ("nội dung " * 100), encoding="utf-8")
    (input_dir / "same.pdf.txt").write_text("QUỐC HỘI\nSố: 99/2025/NĐ-CP\nNGHỊ ĐỊNH\nBẢN PDF", encoding="utf-8")
    wiki_root = tmp_path / "wiki"

    records = scan_folder(input_dir, tmp_path / "db.sqlite", wiki_root=wiki_root, write_wiki=True)

    assert len(records) == 2
    assert {Path(record.wiki_path or "").name for record in records} == {"99_2025_NĐ-CP.md"}
    assert sorted(path.name for path in wiki_root.glob("*.md") if path.name not in {"index.md", "log.md"}) == ["99_2025_NĐ-CP.md"]
    assert "BẢN DOCX ĐẦY ĐỦ" in (wiki_root / "99_2025_NĐ-CP.md").read_text(encoding="utf-8")


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
        write_wiki=True,
    )

    actions = [event[3] for event in events]
    assert "Đang OCR/trích xuất metadata" in actions
    assert "Đang bổ sung metadata" in actions
    assert "Đang lưu DB" in actions
    assert "Đang xuất CSV" in actions
    assert "Đang tạo wiki" in actions

def test_sync_folder_skips_hash_and_extract_for_unchanged_files(tmp_path: Path, monkeypatch) -> None:
    input_dir = tmp_path / "input"
    input_dir.mkdir()
    (input_dir / "one.txt").write_text("Số: 01/2026/QH15\nLUẬT", encoding="utf-8")
    db_path = tmp_path / "db.sqlite"
    sync_folder(input_dir, db_path, wiki_root=tmp_path / "wiki", options=ScanOptions())

    monkeypatch.setattr("phanloaivanban.pipeline.sha256_file", lambda path: (_ for _ in ()).throw(AssertionError("hashed")))
    monkeypatch.setattr("phanloaivanban.pipeline.extract_text", lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("extracted")))

    records, deleted = sync_folder(input_dir, db_path, wiki_root=tmp_path / "wiki", options=ScanOptions())
    assert records == []
    assert deleted == 0

def test_sync_folder_backfills_missing_wiki_with_full_text(tmp_path: Path, monkeypatch) -> None:
    input_dir = tmp_path / "input"
    input_dir.mkdir()
    (input_dir / "law.txt").write_text("QUỐC HỘI\nSố: 12/2026/QH15\nLUẬT\nNội dung", encoding="utf-8")
    db_path = tmp_path / "db.sqlite"
    wiki_root = tmp_path / "wiki"
    sync_folder(input_dir, db_path, wiki_root=wiki_root, options=ScanOptions(build_wiki=False))

    calls = []
    def fake_extract(path, **kwargs):
        calls.append(kwargs)
        return "QUỐC HỘI\nSố: 12/2026/QH15\nLUẬT\nNội dung toàn văn", "ok", None
    monkeypatch.setattr("phanloaivanban.pipeline.extract_text", fake_extract)

    records, deleted = sync_folder(input_dir, db_path, wiki_root=wiki_root)

    assert deleted == 0
    assert len(records) == 1
    assert calls == [{"full_text": True, "ocr_pages": 2}]
    assert Path(records[0].wiki_path or "").name == "12_2026_QH15.md"
    assert Path(records[0].wiki_path or "").is_file()
    assert "Nội dung toàn văn" in Path(records[0].wiki_path or "").read_text(encoding="utf-8")

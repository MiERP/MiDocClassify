from pathlib import Path

from phanloaivanban.pipeline import scan_folder


def test_scan_folder_persists_records_without_wiki_or_llm(tmp_path: Path) -> None:
    input_dir = tmp_path / "input"
    input_dir.mkdir()
    (input_dir / "01_2026_QH15.txt").write_text("Số: 01/2026/QH15\nQUỐC HỘI\nLuật\nNội dung", encoding="utf-8")
    db_path = tmp_path / "records.sqlite"
    csv_path = tmp_path / "records.csv"
    events: list[tuple[int, int, str, str]] = []

    records = scan_folder(
        input_dir,
        db_path,
        csv_path,
        progress_callback=lambda current, total, path, stage: events.append((current, total, path.name, stage)),
    )

    assert len(records) == 1
    assert records[0].file_name == "01_2026_QH15.txt"
    assert records[0].link_goc and records[0].link_goc.startswith("file://")
    assert csv_path.exists()
    assert not (tmp_path / "wiki").exists()
    assert "Đã đọc nội dung" in [event[3] for event in events]

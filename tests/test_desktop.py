from __future__ import annotations

from pathlib import Path

from phanloaivanban.desktop import (
    VISIBLE_FIELDS,
    _document_limit_text,
    _folder_filter,
    _filter_rows,
    _folder_signature,
    _infer_folder_from_rows,
    _is_review_value,
    _load_selected_folder,
    _open_path_from_row,
    _progress_text,
    _save_selected_folder,
    _select_fields,
    _status_text,
)
from phanloaivanban.pipeline import MAX_DOCUMENTS, iter_documents
from phanloaivanban.storage import FIELDS


def test_desktop_review_helpers_report_counts_and_truthy_values() -> None:
    assert _is_review_value(1) is True
    assert _is_review_value("true") is True
    assert _is_review_value(0) is False
    assert _status_text(4) == "Đã tải 4 file."
    assert _status_text(3, "Đã quét") == "Đã quét 3 file."


def test_desktop_select_fields_tolerates_legacy_missing_review_reason() -> None:
    legacy_columns = set(FIELDS) - {"review_reason"}

    selected = _select_fields(legacy_columns)

    assert selected[FIELDS.index("review_reason")] == "''"
    assert selected[FIELDS.index("needs_review")] == "needs_review"
    assert selected[FIELDS.index("extraction_status")] == "extraction_status"


def test_desktop_progress_text_reports_percentage_and_empty_folder() -> None:
    assert _progress_text(2, 5, "a.pdf") == "Đang xử lý 2/5 file (40%) - a.pdf"
    assert _progress_text(5, 5, "a.pdf", "Đang xuất CSV") == "Đang xử lý 5/5 file (100%) - Đang xuất CSV - a.pdf"
    assert _progress_text(0, 0) == "Không tìm thấy file được hỗ trợ trong thư mục đã chọn."

def test_document_limit_reports_error_only_above_limit() -> None:
    assert _document_limit_text(MAX_DOCUMENTS) is None
    assert _document_limit_text(MAX_DOCUMENTS + 1) == "Lỗi: chỉ hỗ trợ tối đa 30 tài liệu; hệ thống chỉ nạp 30 tài liệu đầu tiên."

def test_iter_documents_limits_to_first_30_supported_files(tmp_path: Path) -> None:
    for index in range(31):
        (tmp_path / f"{index:02}.txt").write_text("x", encoding="utf-8")

    documents = iter_documents(tmp_path, MAX_DOCUMENTS)

    assert len(documents) == MAX_DOCUMENTS
    assert documents[-1].name == "29.txt"


def test_desktop_folder_filter_limits_rows_to_selected_folder() -> None:
    clause, params = _folder_filter(Path(r"D:\PROJECT\docs\1"))

    assert clause == " WHERE original_path LIKE ? OR original_path LIKE ?"
    assert params == (r"D:\PROJECT\docs\1\%", r"D:\PROJECT\docs\1/%")


def test_desktop_visible_fields_are_user_facing_only() -> None:
    assert VISIBLE_FIELDS == [
        "so_van_ban",
        "ten_van_ban",
        "co_quan_phat_hanh",
        "ngay_ban_hanh",
        "loai_van_ban",
        "trich_yeu",
    ]


def test_open_path_from_row_prefers_file_uri() -> None:
    assert _open_path_from_row({"link_goc": "file:///D:/a.pdf", "original_path": "D:/b.pdf"}) == "file:///D:/a.pdf"


def test_folder_signature_changes_when_folder_contents_change(tmp_path: Path) -> None:
    folder = tmp_path / "docs"
    folder.mkdir()
    before = _folder_signature(folder)

    (folder / "a.txt").write_text("hello", encoding="utf-8")
    after_add = _folder_signature(folder)
    (folder / "a.txt").unlink()
    after_delete = _folder_signature(folder)

    assert before != after_add
    assert after_delete == before


def test_selected_folder_state_round_trip(tmp_path: Path, monkeypatch) -> None:
    state_path = tmp_path / "state.txt"
    folder = tmp_path / "docs"
    folder.mkdir()
    monkeypatch.setattr("phanloaivanban.desktop.APP_STATE_PATH", state_path)

    _save_selected_folder(folder)

    assert _load_selected_folder() == folder


def test_infer_folder_from_original_paths() -> None:
    rows = [
        {"original_path": r"data-template\a.pdf"},
        {"original_path": r"D:\PROJECT\docs\1\a.pdf"},
        {"original_path": r"D:\PROJECT\docs\1\b.docx"},
    ]

    assert _infer_folder_from_rows(rows) == Path(r"D:\PROJECT\docs\1")


def test_filter_rows_matches_partial_and_accentless_text() -> None:
    rows = [
        {"ten_van_ban": "Luật Công nghệ thông tin"},
        {"ten_van_ban": "Luật Dữ liệu"},
    ]

    assert _filter_rows(rows, "ten_van_ban", "cong nghe") == [rows[0]]
    assert _filter_rows(rows, "ten_van_ban", "") == rows

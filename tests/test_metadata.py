from __future__ import annotations

from pathlib import Path

from phanloaivanban.extractors import extract_text, sha256_file
from phanloaivanban.metadata import (
    enrich_record,
    extract_ngay_ban_hanh,
    extract_so_from_filename,
    extract_title_from_filename,
)
from phanloaivanban.models import DocumentRecord

DEFAULT_TAXONOMY = {
    "document_types": {
        "luat": {"label": "Lu\u1eadt", "patterns": [r"\bLU\u1eacT\b", r"\bQH\d+\b"]},
    },
    "agency_markers": ["\u1ee6Y BAN NH\u00c2N D\u00c2N", "UBND", "B\u1ed8 ", "S\u1ede "],
}


def test_extract_so_from_filename_normalizes_qh_number() -> None:
    assert extract_so_from_filename("7_2022_QH15_any.doc") == "07/2022/QH15"


def test_extract_ngay_ban_hanh_matches_luat_so_header() -> None:
    text = "Lu\u1eadt s\u1ed1: 71/2025/QH15 H\u00e0 N\u1ed9i, ng\u00e0y 14 th\u00e1ng 6 n\u0103m 2025"
    assert extract_ngay_ban_hanh(text) == "2025-06-14"


def test_extract_title_from_filename_strips_numeric_prefix() -> None:
    assert extract_title_from_filename("67_2006_QH11_lu\u1eadt c\u00f4ng ngh\u1ec7 th\u00f4ng tin.docx") == "Lu\u1eadt c\u00f4ng ngh\u1ec7 th\u00f4ng tin"


def test_qh_law_infers_quoc_hoi_agency_from_number() -> None:
    record = DocumentRecord(
        original_path=Path("67.docx"),
        file_name="67_2006_QH11_luat_cong_nghe_thong_tin.docx",
        file_hash="abc",
        extracted_text="LU\u1eacT\nCONG NGHE THONG TIN",
    )

    result = enrich_record(record, DEFAULT_TAXONOMY)

    assert result.so_van_ban == "67/2006/QH11"
    assert result.co_quan_phat_hanh == "Qu\u1ed1c h\u1ed9i"
    assert result.needs_review is False


def test_template_1_doc_fallback_uses_equivalent_sources() -> None:
    folder = Path("data-template/1")
    text, status, ocr_engine = extract_text(folder / "60_2024_QH15_621343.doc")

    assert status == "ok"
    assert ocr_engine is not None and ocr_engine.startswith("equivalent:")
    assert "LU\u1eacT" in text
    assert "D\u1eee LI\u1ec6U" in text


def test_template_1_documents_extract_expected_metadata() -> None:
    folder = Path("data-template/1")
    expected = {
        "07_2022_QH15_458435.doc": ("S\u1eeda \u0111\u1ed5i, b\u1ed5 sung m\u1ed9t s\u1ed1 \u0111i\u1ec1u c\u1ee7a lu\u1eadt s\u1edf h\u1eefu tr\u00ed tu\u1ec7", "2022-06-16"),
        "24_2018_QH14_351416.docx": ("An ninh m\u1ea1ng", "2018-06-12"),
        "38_2024_QH15_555033.pdf": ("Lu\u1eadt c\u00f4ng nghi\u1ec7p qu\u1ed1c ph\u00f2ng, an ninh v\u00e0 \u0111\u1ed9ng vi\u00ean c\u00f4ng nghi\u1ec7p", "2024-06-27"),
        "60_2024_QH15_621343.doc": ("Lu\u1eadt d\u1eef li\u1ec7u", "2024-11-30"),
        "67_2006_QH11_lu\u1eadt c\u00f4ng ngh\u1ec7 th\u00f4ng tin.docx": ("Lu\u1eadt c\u00f4ng ngh\u1ec7 th\u00f4ng tin", "2006-06-29"),
        "71_2025_QH15_lu\u1eadt c\u00f4ng nghi\u1ec7p c\u00f4ng ngh\u1ec7 s\u1ed1.pdf": ("Lu\u1eadt c\u00f4ng nghi\u1ec7p c\u00f4ng ngh\u1ec7 s\u1ed1", "2025-06-14"),
        "93_2025_QH15_581164.pdf": ("Lu\u1eadt khoa h\u1ecdc, c\u00f4ng ngh\u1ec7 v\u00e0 \u0111\u1ed5i m\u1edbi s\u00e1ng t\u1ea1o", "2025-06-27"),
    }

    for file_name, (title, date) in expected.items():
        path = folder / file_name
        text, status, ocr_engine = extract_text(path)
        record = DocumentRecord(
            original_path=path,
            file_name=path.name,
            file_hash=sha256_file(path),
            extracted_text=text,
            extraction_status=status,
            ocr_engine=ocr_engine,
        )

        result = enrich_record(record, DEFAULT_TAXONOMY)

        assert result.extraction_status == "ok"
        assert result.ten_van_ban == title
        assert result.co_quan_phat_hanh == "Qu\u1ed1c h\u1ed9i"
        assert result.ngay_ban_hanh == date
        assert result.trich_yeu
        assert result.needs_review is False


def test_template_2_decision_extracts_header_positions() -> None:
    path = Path("data-template/2/1202_QD-TTg_713288.docx")
    text, status, ocr_engine = extract_text(path)
    record = DocumentRecord(
        original_path=path,
        file_name=path.name,
        file_hash=sha256_file(path),
        extracted_text=text,
        extraction_status=status,
        ocr_engine=ocr_engine,
    )

    result = enrich_record(record, DEFAULT_TAXONOMY)

    assert result.so_van_ban == "1202/QĐ-TTg"
    assert result.ten_van_ban == "Phê duyệt đề án đào tạo phát triển nguồn nhân lực cho lĩnh vực tiêu chuẩn, đo lường, chất lượng trong phạm vi cả nước đến năm 2030 và những năm tiếp theo"
    assert result.co_quan_phat_hanh == "THỦ TƯỚNG CHÍNH PHỦ"
    assert result.ngay_ban_hanh == "2026-07-03"
    assert result.loai_van_ban == "Quyết định"
    assert result.needs_review is False


def test_template_2_pdf_handwritten_number_and_agency_recovery() -> None:
    path = Path("data-template/2/713287.pdf")
    text, status, ocr_engine = extract_text(path)
    record = DocumentRecord(
        original_path=path,
        file_name=path.name,
        file_hash=sha256_file(path),
        extracted_text=text,
        extraction_status=status,
        ocr_engine=ocr_engine,
    )

    result = enrich_record(record, DEFAULT_TAXONOMY)

    assert result.so_van_ban == "97/2026/TT-BQP"
    assert result.co_quan_phat_hanh == "BỘ QUỐC PHÒNG"
    assert result.ngay_ban_hanh == "2026-07-03"
    assert result.loai_van_ban == "Thông tư"

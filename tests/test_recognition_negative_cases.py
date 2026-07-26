from __future__ import annotations

from pathlib import Path

from golden_cases import norm_ascii, parse_filename
from phanloaivanban.extractors import extract_text
from phanloaivanban.metadata import enrich_record
from phanloaivanban.models import DocumentRecord
from phanloaivanban.taxonomy import load_taxonomy


def _record(path: Path, text: str, status: str = "ok") -> DocumentRecord:
    return DocumentRecord(
        original_path=path,
        file_name=path.name,
        file_hash="",
        extracted_text=text,
        extraction_status=status,
    )


def test_filename_parser_handles_missing_year_and_skips_no_signal_file() -> None:
    case = parse_filename("1202_QD-TTg_713288")

    assert case is not None
    assert case.expected_so == "1202/QD-TTg"
    assert case.expected_loai == "Quyết định"
    assert case.expected_co_quan == "Thủ tướng Chính phủ"
    assert case.expected_year is None
    assert parse_filename("93_Anh") is None


def test_content_beats_misleading_filename(tmp_path: Path) -> None:
    path = tmp_path / "999_QD-TTg_wrong.txt"
    path.write_text(
        "QUỐC HỘI\n"
        "Luật số: 67/2006/QH11\n"
        "LUẬT\n"
        "CÔNG NGHỆ THÔNG TIN\n"
        "Hà Nội, ngày 29 tháng 6 năm 2006\n",
        encoding="utf-8",
    )
    text, status, _ = extract_text(path)

    result = enrich_record(_record(path, text, status), load_taxonomy())

    assert result.so_van_ban == "67/2006/QH11"
    assert result.loai_van_ban == "Luật"
    assert result.co_quan_phat_hanh == "Quốc hội"
    assert result.ngay_ban_hanh == "2006-06-29"


def test_preamble_mentions_many_legal_types_but_header_wins(tmp_path: Path) -> None:
    path = tmp_path / "1202_QD-TTg_713288.txt"
    path.write_text(
        "THỦ TƯỚNG CHÍNH PHỦ\n"
        "Số: 1202/QĐ-TTg\n"
        "QUYẾT ĐỊNH\n"
        "Về việc kiểm thử nhận diện\n"
        "Căn cứ Luật Tổ chức Chính phủ;\n"
        "Căn cứ Nghị định số 99/2025/NĐ-CP;\n"
        "Căn cứ Thông tư số 01/2025/TT-BTTTT;\n",
        encoding="utf-8",
    )
    text, status, _ = extract_text(path)

    result = enrich_record(_record(path, text, status), load_taxonomy())

    normalized_so = norm_ascii(result.so_van_ban)
    assert "1202" in normalized_so
    assert "QD-TTG" in normalized_so
    assert result.loai_van_ban == "Quyết định"
    assert "THU TUONG" in norm_ascii(result.co_quan_phat_hanh)


def test_bad_extraction_no_usable_text_requires_review() -> None:
    record = DocumentRecord(
        original_path=Path("scan_broken.pdf"),
        file_name="scan_broken.pdf",
        file_hash="broken",
        extracted_text="",
        extraction_status="pypdfium2 not bundled; scanned/text PDF needs parser",
    )

    result = enrich_record(record, load_taxonomy())

    assert result.needs_review is True
    assert result.confidence < 0.8
    assert result.extraction_status != "ok"

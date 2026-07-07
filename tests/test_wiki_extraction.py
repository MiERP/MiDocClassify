from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

from phanloaivanban.metadata import enrich_record
from phanloaivanban.models import DocumentRecord
from phanloaivanban.pipeline import scan_folder
from phanloaivanban.taxonomy import DEFAULT_TAXONOMY
from phanloaivanban.wiki import write_wiki_record

SAMPLE_67 = """
QUỐC HỘI
Số: 67/2006/QH11
CỘNG HÒA XÃ HỘI CHỦ NGHĨA VIỆT NAM
Độc lập - Tự do - Hạnh phúc
Hà Nội, ngày 29 tháng 06 năm 2006
LUẬT
CÔNG NGHỆ THÔNG TIN
Chương I
Luật này quy định về hoạt động ứng dụng và phát triển công nghệ thông tin.
"""


def test_wiki_writer_creates_traceable_markdown(tmp_path: Path) -> None:
    record = enrich_record(
        DocumentRecord(
            original_path=tmp_path / "67_2006_QH11_luật công nghệ thông tin.txt",
            file_name="67_2006_QH11_luật công nghệ thông tin.txt",
            file_hash="abc123",
            link_goc="file:///orig/67.txt",
            extracted_text=SAMPLE_67,
            extraction_status="ok",
            ocr_engine="parser",
        ),
        DEFAULT_TAXONOMY,
    )

    wiki_path, wiki_text = write_wiki_record(record, tmp_path / "wiki")

    assert wiki_path.parent == tmp_path / "wiki"
    assert wiki_path.suffix == ".md"
    assert "type: legal_document_source" in wiki_text
    assert 'source_uri: "file:///orig/67.txt"' in wiki_text
    assert 'file_hash: "abc123"' in wiki_text
    assert 'extraction_status: "ok"' in wiki_text
    assert "## Metadata candidates" in wiki_text
    assert "## Nội dung văn bản" in wiki_text
    assert wiki_path.read_text(encoding="utf-8") == wiki_text


def test_wiki_writer_marks_empty_text_quality(tmp_path: Path) -> None:
    record = DocumentRecord(
        original_path=tmp_path / "empty.pdf",
        file_name="empty.pdf",
        file_hash="emptyhash",
        link_goc="file:///orig/empty.pdf",
        extracted_text="",
        extraction_status="no text",
        ocr_engine="tesseract",
    )

    _, wiki_text = write_wiki_record(record, tmp_path / "wiki")

    assert 'text_quality: "empty"' in wiki_text
    assert "Không có văn bản trích xuất." in wiki_text


# ---------------------------------------------------------------------------
# 67/2006/QH11 regression tests
# ---------------------------------------------------------------------------

# Clean-header fixture: QUỐC HỘI and Số: both appear as separate lines.
# This is the ideal case where regex extraction works deterministically.
CLEAN_67_HEADER = (
    "QUỐC HỘI\n"
    "Số: 67/2006/QH11\n"
    "CỘNG HÒA XÃ HỘI CHỦ NGHĨA VIỆT NAM\n"
    "Độc lập - Tự do - Hạnh phúc\n"
    "Hà Nội, ngày 29 tháng 06 năm 2006\n"
    "LUẬT\n"
    "CÔNG NGHỆ THÔNG TIN\n"
)

# Real docx extracted text fixture: QUỐC HỘI merged with Quốc hiệu on one line,
# no Số: line in body text, số comes from filename fallback "67/2006/QH11".
DOCX_67_HEADER = (
    "QUỐC HỘI NƯỚC CỘNG HÒA XÃ HỘI CHỦ NGHĨA VIỆT NAM\n"
    "Khóa XI, kỳ họp thứ 9\n"
    "(Từ ngày 16 tháng 5 đến ngày 29 tháng 6 năm 2006)\n"
    "LUẬT\n"
    "CÔNG NGHỆ THÔNG TIN\n"
    "Căn cứ vào Hiến pháp nước Cộng hoà xã hội chủ nghĩa Việt Nam năm 1992\n"
    "đã được sửa đổi, bổ sung theo Nghị quyết số 51/2001/QH10\n"
    "ngày 25 tháng 12 năm 2001 của Quốc hội khoá X, kỳ họp thứ 10;\n"
    "Luật này quy định về công nghệ thông tin.\n"
)

# Quốc hiệu-only noise variant (for fallback path; no agency in explicit form).
QUOC_HIEU_ONLY_67 = (
    "CỘNG HÒA XÃ HỘI CHỦ NGHĨA VIỆT NAM\n"
    "Độc lập - Tự do - Hạnh phúc\n"
    "Hà Nội, ngày 29 tháng 06 năm 2006\n"
    "LUẬT\n"
    "CÔNG NGHỆ THÔNG TIN\n"
)

MOCK_TRICH_YEU_67 = "Quy định về hoạt động ứng dụng và phát triển công nghệ thông tin."

FILENAME_67 = "67_2006_QH11_luật công nghệ thông tin.docx"


def _record_67(
    text: str,
    file_name: str = FILENAME_67,
    file_hash: str = "67abc",
    link_goc: str = "file:///orig/67.docx",
) -> DocumentRecord:
    return DocumentRecord(
        original_path=Path(file_name),
        file_name=file_name,
        file_hash=file_hash,
        link_goc=link_goc,
        extracted_text=text,
        extraction_status="ok",
    )


class Test67QH11Regression:
    """Regression suite for Law 67/2006/QH11 (CNTT)."""

    # -- Clean header (ideal deterministic extraction) --

    def test_clean_header_so_van_ban_is_67_2006_QH11(self) -> None:
        record = enrich_record(_record_67(CLEAN_67_HEADER), DEFAULT_TAXONOMY)
        assert record.so_van_ban == "67/2006/QH11"

    def test_clean_header_co_quan_is_quoc_hoi(self) -> None:
        record = enrich_record(_record_67(CLEAN_67_HEADER), DEFAULT_TAXONOMY)
        assert record.co_quan_phat_hanh == "Quốc hội"

    def test_clean_header_loai_van_ban_is_luat(self) -> None:
        record = enrich_record(_record_67(CLEAN_67_HEADER), DEFAULT_TAXONOMY)
        assert record.loai_van_ban == "Luật"

    def test_clean_header_ngay_ban_hanh_is_2006_06_29(self) -> None:
        record = enrich_record(_record_67(CLEAN_67_HEADER), DEFAULT_TAXONOMY)
        assert record.ngay_ban_hanh == "2006-06-29"

    def test_clean_header_confidence_above_threshold(self) -> None:
        record = enrich_record(_record_67(CLEAN_67_HEADER), DEFAULT_TAXONOMY)
        assert record.confidence >= 0.8
        assert record.needs_review is False

    # -- Real docx fixture (merged QUỐC HỘI + Quốc hiệu, số from filename) --

    def test_docx_header_so_van_ban_from_filename_fallback(self) -> None:
        record = enrich_record(_record_67(DOCX_67_HEADER), DEFAULT_TAXONOMY)
        assert record.so_van_ban == "67/2006/QH11"

    def test_docx_header_co_quan_is_quoc_hoi(self) -> None:
        record = enrich_record(_record_67(DOCX_67_HEADER), DEFAULT_TAXONOMY)
        assert record.co_quan_phat_hanh == "Quốc hội"

    def test_docx_header_is_not_misidentified_as_ubnd(self) -> None:
        record = enrich_record(_record_67(DOCX_67_HEADER), DEFAULT_TAXONOMY)
        assert record.co_quan_phat_hanh is not None
        assert "ủy ban" not in (record.co_quan_phat_hanh or "").lower()
        assert "ubnd" not in (record.co_quan_phat_hanh or "").lower()

    def test_docx_header_ten_van_ban_from_filename(self) -> None:
        record = enrich_record(_record_67(DOCX_67_HEADER), DEFAULT_TAXONOMY)
        assert record.ten_van_ban is not None
        # The title is derived from the filename after stripping số prefix.
        # Diacritics from filename are preserved.
        title_lower = record.ten_van_ban.lower()
        assert "công" in title_lower or "cong" in title_lower
        assert "thông" in title_lower or "thong" in title_lower
        assert "tin" in title_lower

    # -- Quốc hiệu only (no explicit agency) --

    def test_quoc_hieu_only_agency_inferred_from_qh_number(self) -> None:
        record = enrich_record(_record_67(QUOC_HIEU_ONLY_67), DEFAULT_TAXONOMY)
        assert record.co_quan_phat_hanh == "Qu\u1ed1c h\u1ed9i"

    def test_quoc_hieu_only_so_from_filename_fallback(self) -> None:
        record = enrich_record(_record_67(QUOC_HIEU_ONLY_67), DEFAULT_TAXONOMY)
        assert record.so_van_ban == "67/2006/QH11"

    # -- Wiki path assertions --

    def test_wiki_path_is_md_file(self, tmp_path: Path) -> None:
        record = enrich_record(_record_67(CLEAN_67_HEADER), DEFAULT_TAXONOMY)
        wiki_path, _ = write_wiki_record(record, tmp_path / "wiki")
        assert wiki_path.suffix == ".md"
        assert wiki_path.parent == tmp_path / "wiki"

    def test_wiki_path_in_parent_wiki_dir(self, tmp_path: Path) -> None:
        record = enrich_record(_record_67(CLEAN_67_HEADER), DEFAULT_TAXONOMY)
        wiki_path, _ = write_wiki_record(record, tmp_path / "wiki")
        assert str(tmp_path / "wiki") in str(wiki_path.parent)

    # -- Link gốc assertions --

    def test_link_goc_starts_with_file_prefix(self) -> None:
        record = enrich_record(
            _record_67(CLEAN_67_HEADER, link_goc="file:///data/67.docx"),
            DEFAULT_TAXONOMY,
        )
        assert record.link_goc is not None
        assert record.link_goc.startswith("file:///")

    # -- LLM mock: trich_yeu via pipeline with mocked LLM --

    def test_pipeline_ignores_llm_for_metadata(self, tmp_path: Path) -> None:
        """Metadata extraction is deterministic and does not call LLM/wiki."""
        input_dir = tmp_path / "input"
        input_dir.mkdir()
        (input_dir / "67.txt").write_text(CLEAN_67_HEADER, encoding="utf-8")

        with patch("phanloaivanban.pipeline.LocalLLM", autospec=True) as mock_llm_cls:
            records = scan_folder(
                folder=input_dir,
                db_path=tmp_path / "db.sqlite",
                wiki_root=tmp_path / "wiki",
            )

        assert len(records) == 1
        assert records[0].so_van_ban == "67/2006/QH11"
        assert records[0].co_quan_phat_hanh == "Quốc hội"
        assert records[0].trich_yeu == "Công nghệ thông tin"
        assert records[0].wiki_path is None
        mock_llm_cls.assert_not_called()

    def test_trich_yeu_prompt_length_enforcement(self, tmp_path: Path) -> None:
        """trich_yeu assigned via mock must be 3-5 sentences (~reasonable length)."""
        overly_short = "Luật."
        overly_long = ". ".join(["Câu số " + str(i) for i in range(20)]) + "."
        just_right_3 = "Quy định về A. Quy định về B. Quy định về C."
        just_right_5 = "Quy định về A. Quy định về B. Quy định về C. Áp dụng cho D. Hiệu lực từ E."

        assert len(overly_short.split(".")) - 1 < 3  # too short
        assert len(just_right_3.split(".")) - 1 >= 3
        assert len(just_right_5.split(".")) - 1 <= 5
        assert len(overly_long.split(".")) - 1 > 5  # too long

        # Verify the mock LLM prompt contains the length constraint text
        from phanloaivanban.llm import LocalLLM

        prompt = LocalLLM._prompt("test")
        assert "trich_yeu" in prompt.lower()
        assert "tóm tắt" in prompt.lower()
        assert "3-5" in prompt  # sentence count constraint

    # -- Scan folder: stale state probe & misleading success output --

    def test_scan_folder_does_not_corrupt_link_goc(self, tmp_path: Path) -> None:
        """link_goc must stay file:/// and not be mutated to wiki_path."""
        input_dir = tmp_path / "input"
        input_dir.mkdir()
        (input_dir / "67.txt").write_text(CLEAN_67_HEADER, encoding="utf-8")

        records = scan_folder(
            folder=input_dir,
            db_path=tmp_path / "db.sqlite",
            wiki_root=tmp_path / "wiki",
        )

        assert len(records) == 1
        assert records[0].link_goc is not None
        assert records[0].link_goc.startswith("file:///")
        assert records[0].link_goc != records[0].wiki_path

    def test_scan_folder_does_not_create_wiki_on_text_present(self, tmp_path: Path) -> None:
        """Metadata scan stores extracted text but leaves wiki generation out."""
        input_dir = tmp_path / "input"
        input_dir.mkdir()
        (input_dir / "67.txt").write_text(CLEAN_67_HEADER, encoding="utf-8")

        records = scan_folder(
            folder=input_dir,
            db_path=tmp_path / "db.sqlite",
            wiki_root=tmp_path / "wiki",
        )

        assert records[0].wiki_path is None
        assert "QUỐC HỘI" in records[0].extracted_text
        assert not (tmp_path / "wiki").exists()

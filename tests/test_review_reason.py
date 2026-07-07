from __future__ import annotations

import csv
import sqlite3
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

from phanloaivanban import extractors
from phanloaivanban.models import DocumentRecord
from phanloaivanban.pipeline import _backfill_duplicate_versions
from phanloaivanban.storage import export_csv, init_db, upsert_record


def test_storage_persists_and_exports_review_reason(tmp_path: Path) -> None:
    db_path = tmp_path / "records.sqlite"
    csv_path = tmp_path / "records.csv"
    record = DocumentRecord(
        original_path=tmp_path / "sample.docx",
        file_name="sample.docx",
        file_hash="abc",
        extraction_status="ok",
        review_reason="ok",
        needs_review=False,
    )

    init_db(db_path)
    upsert_record(db_path, record)
    export_csv(db_path, csv_path)

    with sqlite3.connect(db_path) as conn:
        stored_reason = conn.execute("SELECT review_reason FROM documents").fetchone()[0]
    rows = list(csv.DictReader(csv_path.open(encoding="utf-8-sig", newline="")))

    assert stored_reason == "ok"
    assert rows[0]["review_reason"] == "ok"


def test_init_db_adds_review_reason_to_existing_database(tmp_path: Path) -> None:
    db_path = tmp_path / "legacy.sqlite"
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            """
            CREATE TABLE documents (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                original_path TEXT NOT NULL,
                file_name TEXT NOT NULL,
                file_hash TEXT NOT NULL UNIQUE,
                extraction_status TEXT,
                needs_review INTEGER
            )
            """
        )

    init_db(db_path)

    with sqlite3.connect(db_path) as conn:
        columns = {row[1] for row in conn.execute("PRAGMA table_info(documents)")}
    assert "review_reason" in columns


def test_backfill_marks_runtime_missing_doc_with_duplicate_reason(tmp_path: Path) -> None:
    duplicate = DocumentRecord(
        original_path=tmp_path / "123.docx",
        file_name="123.docx",
        file_hash="docx",
        so_van_ban="123/QD",
        ten_van_ban="Decision",
        co_quan_phat_hanh="Agency",
        ngay_ban_hanh="2024-03-05",
        loai_van_ban="Quyết định",
        trich_yeu="Subject",
        extraction_status="ok",
        review_reason="ok",
        confidence=1.0,
        needs_review=False,
    )
    runtime_missing = DocumentRecord(
        original_path=tmp_path / "123.doc",
        file_name="123.doc",
        file_hash="doc",
        so_van_ban="123/QD",
        extraction_status="missing_libreoffice",
        review_reason="missing_parser",
        needs_review=True,
    )

    result = _backfill_duplicate_versions([duplicate, runtime_missing])
    filled = next(record for record in result if record.file_name == "123.doc")

    assert filled.ten_van_ban == "Decision"
    assert filled.co_quan_phat_hanh == "Agency"
    assert filled.needs_review is True
    assert filled.review_reason == "backfilled_from_duplicate_missing_libreoffice"


def test_extract_doc_missing_libreoffice_has_stable_status(tmp_path: Path) -> None:
    source = tmp_path / "source.doc"
    source.write_bytes(b"legacy doc")

    text, status, ocr_engine = extractors.extract_text(source, runtime_dir=tmp_path / "runtime")

    assert text == ""
    assert status == "missing_libreoffice"
    assert ocr_engine is None


def test_extract_doc_conversion_does_not_pollute_source_folder(tmp_path: Path, monkeypatch) -> None:
    source = tmp_path / "source.doc"
    source.write_bytes(b"legacy doc")
    soffice = tmp_path / "runtime" / "libreoffice" / "program" / "soffice.exe"
    soffice.parent.mkdir(parents=True)
    soffice.write_bytes(b"")
    polluted_dir = source.parent / ".converted"

    def fake_run(args, **kwargs):
        output_dir = Path(args[args.index("--outdir") + 1])
        (output_dir / "source.docx").write_bytes(b"converted")
        return subprocess.CompletedProcess(args=args, returncode=0, stdout="", stderr="")

    def fake_docx(converted: Path) -> tuple[str, str, str | None]:
        assert converted.parent != polluted_dir
        assert converted.parent != source.parent
        return "converted text", "ok", None

    monkeypatch.setattr(extractors.subprocess, "run", fake_run)
    monkeypatch.setattr(extractors, "_extract_docx", fake_docx)

    text, status, ocr_engine = extractors.extract_text(source, runtime_dir=tmp_path / "runtime")

    assert text == "converted text"
    assert status == "ok"
    assert ocr_engine is None
    assert not polluted_dir.exists()


class _FakePdfPage:
    def __init__(self, rendered_paths: list[Path]) -> None:
        self.rendered_paths = rendered_paths

    def get_textpage(self):
        return SimpleNamespace(get_text_range=lambda: "")

    def render(self, scale: int):
        assert scale == 2

        def save(path: Path) -> None:
            path.write_bytes(b"png")
            self.rendered_paths.append(path)

        return SimpleNamespace(to_pil=lambda: SimpleNamespace(save=save))


class _FakePdfDocument:
    rendered_paths: list[Path] = []

    def __init__(self, path: str) -> None:
        self.path = path
        self.pages = [_FakePdfPage(self.rendered_paths), _FakePdfPage(self.rendered_paths)]

    def __len__(self) -> int:
        return len(self.pages)

    def __getitem__(self, index: int) -> _FakePdfPage:
        return self.pages[index]


def test_extract_pdf_renders_empty_text_pages_to_temp_images_for_ocr(tmp_path: Path, monkeypatch) -> None:
    source = tmp_path / "scan.pdf"
    source.write_bytes(b"pdf")
    _FakePdfDocument.rendered_paths = []
    monkeypatch.setitem(sys.modules, "pypdfium2", SimpleNamespace(PdfDocument=_FakePdfDocument))

    def fake_extract_image(path: Path, runtime_dir: Path) -> tuple[str, str, str | None]:
        assert path.exists()
        assert path.suffix == ".png"
        assert path.parent != source.parent
        assert runtime_dir == tmp_path / "runtime"
        return f"ocr {path.stem}", "ok", "tesseract"

    monkeypatch.setattr(extractors, "_extract_image", fake_extract_image)

    text, status, ocr_engine = extractors.extract_text(source, runtime_dir=tmp_path / "runtime")

    assert text == "ocr page-1\nocr page-2"
    assert status == "ok"
    assert ocr_engine == "tesseract"
    assert len(_FakePdfDocument.rendered_paths) == 2
    assert all(not path.exists() for path in _FakePdfDocument.rendered_paths)
    assert not list(source.parent.glob("*.png"))


def test_extract_pdf_empty_text_without_bundled_tesseract_returns_runtime_status(tmp_path: Path, monkeypatch) -> None:
    source = tmp_path / "scan.pdf"
    source.write_bytes(b"pdf")
    _FakePdfDocument.rendered_paths = []
    monkeypatch.setitem(sys.modules, "pypdfium2", SimpleNamespace(PdfDocument=_FakePdfDocument))

    text, status, ocr_engine = extractors.extract_text(source, runtime_dir=tmp_path / "runtime")

    assert text == ""
    assert status == "bundled Tesseract not found at runtime/tesseract/tesseract.exe"
    assert ocr_engine == "tesseract"
    assert all(not path.exists() for path in _FakePdfDocument.rendered_paths)
    assert not list(source.parent.glob("*.png"))

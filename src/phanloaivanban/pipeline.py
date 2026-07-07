from __future__ import annotations

from dataclasses import replace
from pathlib import Path
from collections.abc import Callable

from .extractors import SUPPORTED_EXTENSIONS, extract_text, sha256_file
from .metadata import enrich_record
from .models import DocumentRecord
from .storage import delete_records_by_paths, export_csv, folder_file_hashes, init_db, upsert_record
from .taxonomy import load_taxonomy

ProgressCallback = Callable[[int, int, Path, str], None]
MAX_DOCUMENTS = 30


def _review_reason(path: Path, extraction_status: str) -> str:
    if extraction_status == "ok":
        return "ok"
    if path.suffix.lower() == ".doc" and (
        extraction_status == "missing_libreoffice" or "LibreOffice" in extraction_status
    ):
        return "missing_parser"
    if "OCR" in extraction_status or "Tesseract" in extraction_status or "no text" in extraction_status:
        return "needs_ocr_runtime"
    return "missing_parser"


def iter_documents(folder: Path, limit: int | None = None) -> list[Path]:
    paths = sorted(path for path in folder.rglob("*") if path.is_file() and path.suffix.lower() in SUPPORTED_EXTENSIONS)
    return paths[:limit] if limit is not None else paths


def scan_folder(
    folder: Path,
    db_path: Path,
    csv_path: Path | None = None,
    progress_callback: ProgressCallback | None = None,
) -> list[DocumentRecord]:
    return _process_paths(iter_documents(folder, MAX_DOCUMENTS), db_path, csv_path, progress_callback)


def sync_folder(
    folder: Path,
    db_path: Path,
    csv_path: Path | None = None,
    progress_callback: ProgressCallback | None = None,
) -> tuple[list[DocumentRecord], int]:
    init_db(db_path)
    current_paths = iter_documents(folder, MAX_DOCUMENTS)
    current_hashes = {str(path): sha256_file(path) for path in current_paths}
    stored_hashes = folder_file_hashes(db_path, folder)
    removed_paths = [Path(path) for path in stored_hashes if path not in current_hashes]
    changed_paths = [Path(path) for path, file_hash in current_hashes.items() if stored_hashes.get(path) != file_hash]
    deleted = delete_records_by_paths(db_path, removed_paths + changed_paths)
    records = _process_paths(changed_paths, db_path, None, progress_callback) if changed_paths else []
    if csv_path:
        export_csv(db_path, csv_path)
    return records, deleted


def _process_paths(
    paths: list[Path],
    db_path: Path,
    csv_path: Path | None,
    progress_callback: ProgressCallback | None = None,
) -> list[DocumentRecord]:
    taxonomy = load_taxonomy()
    init_db(db_path)
    records: list[DocumentRecord] = []
    total = len(paths)
    for index, path in enumerate(paths, start=1):
        _report_progress(progress_callback, index, total, path, _extract_stage(path))
        text, status, ocr_engine = extract_text(path)
        record = DocumentRecord(
            original_path=path,
            file_name=path.name,
            file_hash=sha256_file(path),
            link_goc=path.resolve().as_uri(),
            extracted_text=text,
            extraction_status=status,
            review_reason=_review_reason(path, status),
            ocr_engine=ocr_engine,
        )
        records.append(enrich_record(record, taxonomy))
        _report_progress(progress_callback, index, total, path, "Đã đọc nội dung")
    if records:
        _report_progress(progress_callback, total, total, records[-1].original_path, "Đang bổ sung dữ liệu trùng")
    records = _backfill_duplicate_versions(records)
    for record in records:
        upsert_record(db_path, record)
    if csv_path:
        if records:
            _report_progress(progress_callback, total, total, records[-1].original_path, "Đang xuất CSV")
        export_csv(db_path, csv_path)
    return records


def _report_progress(callback: ProgressCallback | None, current: int, total: int, path: Path, stage: str) -> None:
    if callback is not None:
        callback(current, total, path, stage)


def _extract_stage(path: Path) -> str:
    return "Đang chạy OCR" if path.suffix.lower() in {".pdf", ".png", ".jpg", ".jpeg", ".tif", ".tiff"} else "Đang đọc nội dung"


def _backfill_duplicate_versions(records: list[DocumentRecord]) -> list[DocumentRecord]:
    best_by_number: dict[str, DocumentRecord] = {}
    for record in records:
        if not record.so_van_ban:
            continue
        best = best_by_number.get(record.so_van_ban)
        if best is None or record.confidence > best.confidence:
            best_by_number[record.so_van_ban] = record
    filled: list[DocumentRecord] = []
    for record in records:
        source = best_by_number.get(record.so_van_ban or "")
        if source is None or source is record:
            filled.append(record)
            continue
        patch = {
            "ten_van_ban": record.ten_van_ban or source.ten_van_ban,
            "co_quan_phat_hanh": record.co_quan_phat_hanh or source.co_quan_phat_hanh,
            "ngay_ban_hanh": record.ngay_ban_hanh or source.ngay_ban_hanh,
            "loai_van_ban": record.loai_van_ban or source.loai_van_ban,
            "trich_yeu": record.trich_yeu or source.trich_yeu,
        }
        values = [record.so_van_ban, patch["ten_van_ban"], patch["co_quan_phat_hanh"], patch["ngay_ban_hanh"], patch["loai_van_ban"]]
        confidence = round(sum(1 for value in values if value) / len(values), 2)
        review_reason = record.review_reason
        if record.original_path.suffix.lower() == ".doc" and (
            record.extraction_status == "missing_libreoffice"
            or "LibreOffice" in record.extraction_status
        ):
            review_reason = "backfilled_from_duplicate_missing_libreoffice"
        filled.append(
            replace(
                record,
                **patch,
                confidence=max(record.confidence, confidence),
                needs_review=confidence < 0.8 or record.extraction_status != "ok",
                review_reason=review_reason,
            )
        )
    return filled

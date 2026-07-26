from __future__ import annotations

import os
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, replace
from pathlib import Path

from .extractors import EXTRACTOR_VERSION, SUPPORTED_EXTENSIONS, extract_text, sha256_file
from .log_utils import get_logger
from .metadata import enrich_record
from .models import DocumentRecord
from .storage import all_records, apply_record_changes, export_csv, folder_file_states, init_db, wiki_paths_by_original_paths
from .taxonomy import load_taxonomy
from .wiki import append_wiki_log, remove_unreferenced_wiki_files, remove_wiki_files, wiki_path_for_record, write_wiki_index, write_wiki_record


@dataclass(frozen=True)
class ScanOptions:
    full_text: bool = False
    ocr_pages: int = 2
    workers: int = max(1, min(2, (os.cpu_count() or 2) // 2))
    build_wiki: bool = True
    export_csv: Path | None = None


def _extractor_version(options: ScanOptions) -> str:
    return f"{EXTRACTOR_VERSION}:{'full' if options.full_text or options.build_wiki else 'fast'}"


def _review_reason(path: Path, extraction_status: str) -> str:
    if extraction_status == "ok":
        return "ok"
    if extraction_status == "missing_libreoffice":
        return "missing_parser"
    if extraction_status.startswith(("ocr_", "missing_tesseract", "pdf_no_text")):
        return "needs_ocr_runtime"
    return "missing_parser"


def _progress(progress_callback: Callable[..., None] | None, current: int, total: int, path: Path, action: str) -> None:
    if progress_callback is None:
        return
    try:
        progress_callback(current, total, path, action)
    except TypeError:
        progress_callback(current, total, path)


def iter_documents(folder: Path) -> list[Path]:
    return sorted(path for path in folder.rglob("*") if path.is_file() and path.suffix.lower() in SUPPORTED_EXTENSIONS)


def scan_folder(
    folder: Path,
    db_path: Path,
    csv_path: Path | None = None,
    wiki_root: Path | None = None,
    progress_callback: Callable[..., None] | None = None,
    write_wiki: bool = True,
    options: ScanOptions | None = None,
) -> list[DocumentRecord]:
    options = options or ScanOptions(build_wiki=write_wiki, export_csv=csv_path)
    wiki_root = wiki_root or db_path.parent / "wiki"
    init_db(db_path)
    records = _build_records(iter_documents(folder), progress_callback, options)
    if records:
        _progress(progress_callback, len(records), len(records), records[-1].original_path, "Đang lưu DB")
    apply_record_changes(db_path, records, [])
    records = _write_artifacts(records, db_path, wiki_root, progress_callback, options)
    if options.export_csv:
        if records:
            _progress(progress_callback, len(records), len(records), records[-1].original_path, "Đang xuất CSV")
        export_csv(db_path, options.export_csv)
    return records


def sync_folder(
    folder: Path,
    db_path: Path,
    csv_path: Path | None = None,
    wiki_root: Path | None = None,
    progress_callback: Callable[..., None] | None = None,
    write_wiki: bool = True,
    options: ScanOptions | None = None,
) -> tuple[list[DocumentRecord], int]:
    options = options or ScanOptions(build_wiki=write_wiki, export_csv=csv_path)
    wiki_root = wiki_root or db_path.parent / "wiki"
    init_db(db_path)
    current_paths = iter_documents(folder)
    expected_version = _extractor_version(options)
    current_states = {str(path): (path.stat().st_size, path.stat().st_mtime_ns) for path in current_paths}
    stored_states = folder_file_states(db_path, folder)
    removed_paths = [Path(path) for path in stored_states if path not in current_states]
    changed_paths = [
        Path(path)
        for path, state in current_states.items()
        if stored_states.get(path) != (*state, expected_version)
    ]
    stale_paths = removed_paths + changed_paths
    stale_wiki_paths = wiki_paths_by_original_paths(db_path, stale_paths) if options.build_wiki else []
    records = _build_records(changed_paths, progress_callback, options)
    if records or stale_paths:
        progress_path = records[-1].original_path if records else stale_paths[-1]
        _progress(progress_callback, len(records), len(changed_paths), progress_path, "Đang lưu DB")
    apply_record_changes(db_path, records, stale_paths)
    if options.build_wiki:
        removed_wiki_count = remove_wiki_files(stale_wiki_paths)
        if stale_paths or removed_wiki_count:
            append_wiki_log(wiki_root, "delete", paths=stale_paths)
        current_path_set = set(current_states)
        artifact_records = [
            record for record in all_records(db_path)
            if str(record.original_path) in current_path_set
            and (not record.wiki_path or not Path(record.wiki_path).is_file())
        ]
        records = _write_artifacts(artifact_records, db_path, wiki_root, progress_callback, options)
        if stale_paths and not artifact_records:
            write_wiki_index(all_records(db_path), wiki_root)
    if options.export_csv:
        if records:
            _progress(progress_callback, len(records), len(records), records[-1].original_path, "Đang xuất CSV")
        export_csv(db_path, options.export_csv)
    return records, len(removed_paths)


def _build_records(
    paths: list[Path],
    progress_callback: Callable[..., None] | None,
    options: ScanOptions,
) -> list[DocumentRecord]:
    log = get_logger()
    taxonomy = load_taxonomy()
    total = len(paths)
    log.info("scan_paths: start %d files", total)

    def build(path: Path) -> DocumentRecord:
        stat = path.stat()
        full_text = options.full_text or options.build_wiki
        try:
            text, status, ocr_engine = extract_text(path, full_text=full_text, ocr_pages=options.ocr_pages)
        except Exception as exc:
            text, status, ocr_engine = "", f"extract_error:{type(exc).__name__}", None
        record = DocumentRecord(
            original_path=path,
            file_name=path.name,
            file_hash=sha256_file(path),
            file_size=stat.st_size,
            mtime_ns=stat.st_mtime_ns,
            extractor_version=_extractor_version(options),
            indexed_at=DocumentRecord.indexed_now(),
            link_goc=path.resolve().as_uri(),
            extracted_text=text,
            extraction_status=status,
            review_reason=_review_reason(path, status),
            ocr_engine=ocr_engine,
        )
        return enrich_record(record, taxonomy)

    workers = max(1, min(2, options.workers))
    if workers == 1 or len(paths) < 2:
        records = []
        for index, path in enumerate(paths, 1):
            _progress(progress_callback, index, total, path, "Đang OCR/trích xuất metadata")
            records.append(build(path))
    else:
        with ThreadPoolExecutor(max_workers=workers) as pool:
            records = list(pool.map(build, paths))
        for index, path in enumerate(paths, 1):
            _progress(progress_callback, index, total, path, "Đang OCR/trích xuất metadata")
    if records:
        _progress(progress_callback, total, total, records[-1].original_path, "Đang bổ sung metadata")
    return _backfill_duplicate_versions(records)


def _write_artifacts(
    records: list[DocumentRecord],
    db_path: Path,
    wiki_root: Path,
    progress_callback: Callable[..., None] | None,
    options: ScanOptions,
) -> list[DocumentRecord]:
    if not options.build_wiki:
        return records
    grouped: dict[Path, list[DocumentRecord]] = {}
    for record in records:
        grouped.setdefault(wiki_path_for_record(record, wiki_root), []).append(record)
    with_wiki = []
    for index, (wiki_path, versions) in enumerate(grouped.items(), 1):
        best = max(versions, key=lambda record: (record.extraction_status == "ok", len(record.extracted_text), record.confidence))
        _progress(progress_callback, index, len(grouped), best.original_path, "Đang tạo wiki")
        write_wiki_record(best, wiki_root)
        with_wiki.extend(replace(record, wiki_path=str(wiki_path)) for record in versions)
    if with_wiki:
        append_wiki_log(wiki_root, "ingest", records=with_wiki)
        apply_record_changes(db_path, with_wiki, [])
        _progress(progress_callback, 0, 0, Path(""), "Đang cập nhật wiki index")
        remove_unreferenced_wiki_files(all_records(db_path), wiki_root)
        write_wiki_index(all_records(db_path), wiki_root)
    return with_wiki


def _backfill_duplicate_versions(records: list[DocumentRecord]) -> list[DocumentRecord]:
    best_by_number: dict[str, DocumentRecord] = {}
    for record in records:
        if record.so_van_ban:
            best = best_by_number.get(record.so_van_ban)
            if best is None or record.confidence > best.confidence:
                best_by_number[record.so_van_ban] = record
    filled = []
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
        confidence = round(sum(bool(value) for value in values) / len(values), 2)
        review_reason = record.review_reason
        if record.original_path.suffix.lower() == ".doc" and record.extraction_status == "missing_libreoffice":
            review_reason = "backfilled_from_duplicate_missing_libreoffice"
        filled.append(replace(record, **patch, confidence=max(record.confidence, confidence), needs_review=confidence < 0.8 or record.extraction_status != "ok", review_reason=review_reason))
    return filled

from __future__ import annotations

import re
from datetime import datetime
from pathlib import Path

from .file_utils import atomic_write
from .models import DocumentRecord


METADATA_FIELDS = (
    "so_van_ban",
    "ngay_ban_hanh",
    "loai_van_ban",
    "co_quan_phat_hanh",
    "ten_van_ban",
)


def write_wiki_record(record: DocumentRecord, wiki_root: Path) -> tuple[Path, str]:
    wiki_path = wiki_path_for_record(record, wiki_root)
    wiki_text = _render_wiki(record)
    _atomic_write(wiki_path, wiki_text)
    return wiki_path, wiki_text

def wiki_path_for_record(record: DocumentRecord, wiki_root: Path) -> Path:
    return wiki_root / f"{_wiki_stem(record)}.md"


def write_wiki_index(records: list[DocumentRecord], wiki_root: Path) -> Path:
    index_path = wiki_root / "index.md"
    rows = [
        "# Midoc Wiki Index",
        "",
        f"Tổng số tài liệu: {len(records)}",
        "",
        "| Số văn bản | Loại | Cơ quan | Ngày | Tiêu đề | Wiki | Nguồn | Review |",
        "|---|---|---|---|---|---|---|---|",
    ]
    for record in sorted(records, key=lambda item: (item.ngay_ban_hanh or "", item.so_van_ban or item.file_name)):
        wiki_link = ""
        if record.wiki_path:
            wiki_name = Path(record.wiki_path).name
            wiki_link = f"[{_md_cell(wiki_name)}]({_md_cell(wiki_name)})"
        rows.append(
            "| "
            + " | ".join(
                [
                    _md_cell(record.so_van_ban),
                    _md_cell(record.loai_van_ban),
                    _md_cell(record.co_quan_phat_hanh),
                    _md_cell(record.ngay_ban_hanh),
                    _md_cell(record.ten_van_ban),
                    wiki_link,
                    _md_cell(record.original_path),
                    _md_cell(record.needs_review),
                ]
            )
            + " |"
        )
    _atomic_write(index_path, "\n".join(rows) + "\n")
    return index_path


def append_wiki_log(
    wiki_root: Path,
    action: str,
    records: list[DocumentRecord] | None = None,
    paths: list[Path] | None = None,
) -> Path:
    log_path = wiki_root / "log.md"
    lines = [log_path.read_text(encoding="utf-8").rstrip() if log_path.exists() else "# Midoc Wiki Log", ""]
    lines.append(f"## [{datetime.now().isoformat(timespec='seconds')}] {action}")
    for record in records or []:
        lines.append(f"- {record.so_van_ban or record.file_name} -> {record.wiki_path or ''}")
    for path in paths or []:
        lines.append(f"- {path}")
    _atomic_write(log_path, "\n".join(lines) + "\n")
    return log_path


def remove_wiki_files(paths: list[str | Path | None]) -> int:
    removed = 0
    for value in paths:
        if value is None:
            continue
        path = Path(value)
        if path.suffix.lower() != ".md" or path.name in {"index.md", "log.md"} or not path.exists():
            continue
        path.unlink()
        removed += 1
    return removed

def remove_unreferenced_wiki_files(records: list[DocumentRecord], wiki_root: Path) -> int:
    keep = {Path(record.wiki_path).resolve() for record in records if record.wiki_path}
    removed = 0
    for path in wiki_root.glob("*.md"):
        if path.name in {"index.md", "log.md"} or path.resolve() in keep:
            continue
        path.unlink()
        removed += 1
    return removed


def _atomic_write(path: Path, text: str) -> None:
    atomic_write(path, text)


def _md_cell(value: object) -> str:
    if value is None:
        return ""
    return str(value).replace("|", r"\|").replace("\n", " ")


def _safe_stem(file_hash: str, source_stem: str) -> str:
    digest = re.sub(r"[^A-Za-z0-9_-]+", "-", file_hash).strip("-")[:16]
    stem = re.sub(r"[^\w.-]+", "-", source_stem, flags=re.UNICODE).strip(".-_")[:80]
    return "-".join(part for part in (digest, stem) if part) or "document"

def _wiki_stem(record: DocumentRecord) -> str:
    if record.so_van_ban:
        stem = re.sub(r"[^\w.-]+", "_", record.so_van_ban, flags=re.UNICODE).strip("._-")
        if stem:
            return stem[:120]
    return _safe_stem(record.file_hash, record.original_path.stem)


def _render_wiki(record: DocumentRecord) -> str:
    text = record.extracted_text.strip()
    title = record.ten_van_ban or record.file_name or record.original_path.name
    frontmatter = {
        "type": "legal_document_source",
        "source_path": str(record.original_path),
        "source_uri": record.link_goc or record.original_path.resolve().as_uri(),
        "file_hash": record.file_hash,
        "original_filename": record.file_name,
        "extraction_status": record.extraction_status,
        "ocr_engine": record.ocr_engine,
        "text_quality": "empty" if not text else "present",
    }
    for field in METADATA_FIELDS:
        value = getattr(record, field)
        if value:
            frontmatter[field] = value

    notes = [f"Trạng thái trích xuất: {record.extraction_status}."]
    if not text:
        notes.append("Không có văn bản trích xuất.")
    if record.ocr_engine:
        notes.append(f"OCR/parser: {record.ocr_engine}.")

    return "\n".join(
        [
            "---",
            *[f"{key}: {_yaml_value(value)}" for key, value in frontmatter.items()],
            "---",
            "",
            f"# {title}",
            "",
            "## Metadata candidates",
            _metadata_lines(record),
            "",
            "## Header text",
            _header_text(text),
            "",
            "## Nội dung văn bản",
            text or "Không có văn bản trích xuất.",
            "",
            "## Ghi chú trích xuất",
            "\n".join(f"- {note}" for note in notes),
            "",
        ]
    )


def _yaml_value(value: object) -> str:
    if value is None:
        return "null"
    if value == "legal_document_source":
        return str(value)
    escaped = str(value).replace("\\", "\\\\").replace('"', '\\"')
    return f'"{escaped}"'


def _metadata_lines(record: DocumentRecord) -> str:
    lines = []
    for field in METADATA_FIELDS:
        value = getattr(record, field)
        lines.append(f"- {field}: {value or 'null'}")
    return "\n".join(lines)


def _header_text(text: str) -> str:
    if not text:
        return "Không có văn bản trích xuất."
    return "\n".join(text.splitlines()[:20])

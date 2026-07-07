from __future__ import annotations

import re
from pathlib import Path

from .models import DocumentRecord


METADATA_FIELDS = (
    "so_van_ban",
    "ngay_ban_hanh",
    "loai_van_ban",
    "co_quan_phat_hanh",
    "ten_van_ban",
)


def write_wiki_record(record: DocumentRecord, wiki_root: Path) -> tuple[Path, str]:
    wiki_root.mkdir(parents=True, exist_ok=True)
    wiki_path = wiki_root / f"{_safe_stem(record.file_hash, record.original_path.stem)}.md"
    wiki_text = _render_wiki(record)
    wiki_path.write_text(wiki_text, encoding="utf-8")
    return wiki_path, wiki_text


def _safe_stem(file_hash: str, source_stem: str) -> str:
    digest = re.sub(r"[^A-Za-z0-9_-]+", "-", file_hash).strip("-")[:16]
    stem = re.sub(r"[^\w.-]+", "-", source_stem, flags=re.UNICODE).strip(".-_")[:80]
    return "-".join(part for part in (digest, stem) if part) or "document"


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

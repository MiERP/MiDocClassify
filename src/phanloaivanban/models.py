from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class DocumentRecord:
    original_path: Path
    file_name: str
    file_hash: str
    so_van_ban: str | None = None
    ten_van_ban: str | None = None
    co_quan_phat_hanh: str | None = None
    ngay_ban_hanh: str | None = None
    loai_van_ban: str | None = None
    trich_yeu: str | None = None
    link_goc: str | None = None
    extracted_text: str = ""
    extraction_status: str = "ok"
    review_reason: str = "ok"
    ocr_engine: str | None = None
    confidence: float = 0.0
    needs_review: bool = True
